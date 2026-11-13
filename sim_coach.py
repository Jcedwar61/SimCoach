# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = [
#   "numpy",
#   "pygame>=2.5",
#   "sounddevice",
#   "faster-whisper>=1.0",
#   "edge-tts>=6.1",
#   "gTTS>=2.5",
#   "kokoro-onnx>=0.4",
#   "openai>=1.60",
#   "keyboard",
#   "psutil",
#   "segno",
#   "pywin32; sys_platform == 'win32'",
# ]
# ///
"""SimCoach - live English voice coach and race crew for sim racing.
Sims: Assetto Corsa, ACC, AC Rally, AC EVO, Le Mans Ultimate, rFactor 2, AMS2, RaceRoom, EA SPORTS WRC, F1 25, DiRT Rally 2.0.
Options: --console --bind [ptt|repeat|mute|tones] --no-overlay --no-voice --no-mic --test --setup
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import queue
import random
import re
import atexit
import shutil
import struct
import sys
import tempfile
import threading
import textwrap
import time
import traceback
from bisect import bisect_left
from collections import OrderedDict, deque
from dataclasses import dataclass
from functools import lru_cache

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
else:
    ctypes = None
    wintypes = None

for _env_k, _env_v in (("OMP_NUM_THREADS", "2"), ("MKL_NUM_THREADS", "2"), ("OPENBLAS_NUM_THREADS", "2"),
                       ("VECLIB_MAXIMUM_THREADS", "2"), ("NUMEXPR_NUM_THREADS", "2"),
                       ("TOKENIZERS_PARALLELISM", "false"), ("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1"),
                       ("PYGAME_HIDE_SUPPORT_PROMPT", "1")):
    os.environ.setdefault(_env_k, _env_v)

if sys.platform == "win32" and ctypes is not None:
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
    except Exception:
        pass

try:
    import numpy as _np
except Exception:
    _np = None
from typing import Optional

APP_VERSION = "6.11"
APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "SimCoach")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "simcoach.log")
REF_DIR = os.path.join(APP_DIR, "references")
TRACK_DIR = os.path.join(APP_DIR, "tracks")          # starter-lap track shapes downloaded from the library
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = {
    "driver_name": "",
    "voice": "en-GB-RyanNeural",
    "speech_rate": 8,
    "volume": 0.9,
    "audio_out": "",
    "mic": "",
    "whisper_model": "small.en",
    "buttons": {},
    "ptt_key": "f8",
    "openai_api_key": "",
    "openai_model": "gpt-6-luna",
    "openai_stt_model": "gpt-transcribe",
    "ai_provider": "openai",
    "ai_fallback": True,
    "gemini_api_key": "",
    "gemini_model": "gemini-3.5-flash",
    "deepseek_api_key": "",
    "deepseek_model": "deepseek-chat",
    "talk_level": 1,
    "overlay_pedals": True,
    "overlay_locked": False,
    "overlay_pos": None,
    "coach_personality": "mansell",
    "brake_callouts": "focus",
    "split_callouts": False,
    "auto_start": True,
    "f1_port": 20777,
    "dr2_port": 20779,
    "udp_share_simhub": True,
    "engineer_on": True,
    "strategist_on": True,
    "spotter_on": True,
    "engineer_voice": "en-GB-ThomasNeural",
    "strategist_voice": "en-US-AndrewNeural",
    "spotter_voice": "en-AU-WilliamNeural",
    "crew_updates": "important",
    "crew_chatter": "normal",
    "crew_language": "clean",
    "spotter_swap": [],
    "csp_weather_app": True,
    "second_screen": False,
    "second_screen_port": 8765,
    "check_updates": True,
    "briefing_mode": "daily",
    "starter_laps": True,
    "shared_refs": True,
    "sheet_autopop": True,
    "auto_share": False,
    "update_skip": "",
    "library_seen": {},
    "library_tracks_seen": {},
    "shared_laps": {},
    "github_token": "",
    "github_login": "",
    "github_client_id": "",
}
RALLY_GAMES = {"EA WRC", "DiRT Rally 2.0", "AC Rally"}
NO_REFUEL_GAMES = {"F1 25"}
KG_FUEL_GAMES = {"F1 25"}


def fuel_unit(game, n=None):
    u = "kilo" if game in KG_FUEL_GAMES else "litre"
    return u if n == 1 else u + "s"

OPENAI_MODELS = ["gpt-6-luna", "gpt-6.1-terra", "gpt-5.6-luna"]
GEMINI_MODELS = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemini-flash-latest"]
DEEPSEEK_MODELS = ["deepseek-chat", "deepseek-flash", "deepseek-v4-pro", "deepseek-reasoner"]
RETIRED_OPENAI_MODELS = ("gpt-4o", "gpt-4.1", "gpt-4-", "gpt-3.5")
WHISPER_MODELS = [("Fast (base.en)", "base.en"), ("Balanced (small.en)", "small.en"),
                  ("Most accurate (medium.en)", "medium.en"), ("OpenAI online (uses key)", "openai")]

BINS = 2000
LOOP_HZ = 60
GAP_AFTER_TALK = 1.5
LOSS_TO_MENTION = 0.12


def _documents_dir():
    """The real Documents folder (follows OneDrive / moved-folder redirection on Windows)."""
    if sys.platform == "win32" and ctypes is not None:
        try:
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return buf.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


REPORT_DIR = os.path.join(_documents_dir(), "SimCoach Reports")


def ensure_report_dir():
    """Create the reports folder; seed it with the sample report so it's never an empty mystery."""
    try:
        os.makedirs(REPORT_DIR, exist_ok=True)
        sample = os.path.join(SCRIPT_DIR, "sample_coach_report.html")
        if os.path.exists(sample) and not any(f.endswith(".html") for f in os.listdir(REPORT_DIR)):
            shutil.copy2(sample, os.path.join(REPORT_DIR, "sample_coach_report.html"))
    except Exception:
        pass
    return REPORT_DIR


BEEP_LOG = deque(maxlen=300)


def beep(freq=900, ms=140):
    """Fallback tone through the Windows default device (used only when the audio mixer is unavailable)."""
    if sys.platform == "win32":
        def _b():
            try:
                import winsound
                winsound.Beep(freq, ms)
            except Exception:
                pass
        threading.Thread(target=_b, daemon=True).start()


def stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def consistency_of(times):
    """How repeatable a set of clean lap times is: {"sd": seconds, "pct": sd as % of the best lap, "label",
    "laps": laps counted, "off": laps left out}. Laps more than 2 % off the best are left out: early laps while
    the driver is still learning the track, or a lap spoiled by traffic or a moment. So a driver who gets
    quicker through a session isn't called inconsistent for it. None with fewer than 3 laps to judge."""
    times = [t for t in times if t and t > 0]
    if len(times) < 3:
        return None
    best = min(times)
    kept = [t for t in times if t <= best * 1.02]
    if len(kept) < 3:
        return None
    sd = stdev(kept)
    pct = 100.0 * sd / best
    label = ("very consistent" if pct < 0.3 else "consistent" if pct < 0.7 else "a bit up and down" if pct < 1.2
             else "inconsistent")
    return {"sd": sd, "pct": pct, "label": label, "laps": len(kept), "off": len(times) - len(kept)}


def pace_advice(pace_pct, cons):
    """One line on what to work on, from pace (% of the target lap, or None) and consistency_of()'s result."""
    steady = cons is not None and cons["pct"] < 0.7
    if cons is not None and cons["pct"] >= 1.2:
        return "Work on consistency first: aim for five laps within half a second before chasing lap time."
    if pace_pct is None:
        return ("You're repeating your laps well, so start pushing your braking points one corner at a time."
                if steady else "")
    if pace_pct <= 101.0:
        return "That's right on a quick lap. Now it's about doing it every lap."
    if pace_pct <= 103.0:
        return ("Close to a quick lap: the last second is in your focus corners." if steady else
                "You're close to a quick lap: tidy up the lap-to-lap variation and it's there.")
    if steady:
        return "The time is in technique now: work through your focus corners one at a time."
    return "Smooth, repeatable laps first; the pace follows."


_LOG_LOCK = threading.Lock()
_LOG_DIR_READY = False


_LOG_Q: "queue.SimpleQueue[str]" = queue.SimpleQueue()
_LOG_WRITER = None
_LOG_TAP = None


def _log_write_locked(lines):
    """Caller holds _LOG_LOCK."""
    global _LOG_DIR_READY
    try:
        if not _LOG_DIR_READY:
            os.makedirs(APP_DIR, exist_ok=True)
            _LOG_DIR_READY = True
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write("".join(lines))
            rotate = fh.tell() > 2_000_000
        if rotate:
            os.replace(LOG_PATH, LOG_PATH + ".old")
    except Exception:
        pass


def _log_write(lines):
    with _LOG_LOCK:
        _log_write_locked(lines)


def _drain_log(lines, limit=None):
    while limit is None or len(lines) < limit:
        try:
            lines.append(_LOG_Q.get_nowait())
        except queue.Empty:
            break
    return lines


_LOG_EV = threading.Event()


def _log_worker():
    while True:
        _LOG_EV.wait()
        with _LOG_LOCK:
            _LOG_EV.clear()
            lines = _drain_log([], 500)
            if lines:
                _log_write_locked(lines)
            if not _LOG_Q.empty():
                _LOG_EV.set()


def flush_log():
    """Write whatever is still queued, after any batch the writer is busy with (at exit, before a crash report)."""
    with _LOG_LOCK:
        lines = _drain_log([])
        if lines:
            _log_write_locked(lines)


def file_log(msg, sync=False):
    """Append a line to %APPDATA%\\SimCoach\\simcoach.log (rotated at 2 MB). Lines go through a writer thread,
    so the telemetry thread never waits on the disk (or an antivirus scan of it); sync=True writes now."""
    global _LOG_WRITER
    tap = _LOG_TAP
    if tap is not None:
        tap(msg)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n"
    if sync:
        flush_log()
        _log_write([line])
        return
    if _LOG_WRITER is None:
        with _LOG_LOCK:
            if _LOG_WRITER is None:
                _LOG_WRITER = threading.Thread(target=_log_worker, daemon=True, name="log-writer")
                _LOG_WRITER.start()
                atexit.register(flush_log); atexit.register(lambda: (Coach._SAVE_LOCK.acquire(), Coach._SAVE_LOCK.release()))
    _LOG_Q.put(line)
    _LOG_EV.set()


def install_crash_logging():
    import traceback

    def hook(exc_type, exc, tb):
        file_log("CRASH: " + "".join(traceback.format_exception(exc_type, exc, tb)), sync=True)
        sys.__excepthook__(exc_type, exc, tb)

    def thook(args):
        file_log(f"THREAD CRASH ({args.thread.name}): " +
                 "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)), sync=True)
    sys.excepthook = hook
    threading.excepthook = thook


def _sane_num(x):
    try:
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    except OverflowError:
        return False


def _sane_config(cfg):
    """Settings whose saved value has the wrong type (a damaged or hand-edited config.json) get the default."""
    sw = cfg.get("spotter_swap")
    if isinstance(sw, bool):
        cfg["spotter_swap"] = list(SPOTTER_GAMES) if sw else []
    for k, dv in DEFAULT_CONFIG.items():
        if dv is None or k not in cfg:
            continue
        v = cfg[k]
        if isinstance(dv, bool):
            good = isinstance(v, (bool, int))
        elif isinstance(dv, (int, float)):
            good = _sane_num(v)
        elif isinstance(dv, str):
            good = isinstance(v, str)
        elif isinstance(dv, dict):
            good = isinstance(v, dict)
        elif isinstance(dv, list):
            good = isinstance(v, list)
        else:
            good = True
        if not good:
            cfg[k] = json.loads(json.dumps(dv))
    op = cfg.get("overlay_pos")
    if op is not None and not (isinstance(op, (list, tuple)) and len(op) >= 2 and _sane_num(op[0]) and _sane_num(op[1])):
        cfg["overlay_pos"] = None
    if isinstance(cfg.get("spotter_swap"), list):
        cfg["spotter_swap"] = [g for g in cfg["spotter_swap"] if isinstance(g, str)]
    btns = cfg.get("buttons")
    if isinstance(btns, dict):
        cfg["buttons"] = {a: b for a, b in btns.items() if isinstance(a, str) and isinstance(b, dict)
                          and isinstance(b.get("device"), str) and isinstance(b.get("button"), int)
                          and not isinstance(b.get("button"), bool) and b["button"] >= 0}
    for pk in ("f1_port", "dr2_port"):
        pv = cfg.get(pk)
        if not (_sane_num(pv) and 1 <= int(pv) <= 65535):
            cfg[pk] = DEFAULT_CONFIG[pk]
        else:
            cfg[pk] = int(pv)
    cfg["volume"] = max(0.0, min(1.0, float(cfg.get("volume", 0.9))))
    cfg["speech_rate"] = max(-50, min(100, int(round(float(cfg.get("speech_rate", 8))))))
    if cfg.get("talk_level") not in (0, 1, 2):
        cfg["talk_level"] = 1
    if cfg.get("brake_callouts") not in ("focus", "all", "off"):
        cfg["brake_callouts"] = "focus"
    if cfg.get("crew_updates") not in ("every", "every2", "important"):
        cfg["crew_updates"] = DEFAULT_CONFIG["crew_updates"]
    if cfg.get("crew_chatter") not in ("off", "normal", "lots"):
        cfg["crew_chatter"] = "normal"
    if cfg.get("briefing_mode") not in ("daily", "always", "off"):
        cfg["briefing_mode"] = "daily"
    if cfg.get("crew_language") not in ("clean", "salty"):
        cfg["crew_language"] = "clean"
    sp = cfg.get("second_screen_port")
    cfg["second_screen_port"] = int(sp) if _sane_num(sp) and 1024 <= int(sp) <= 65535 else 8765


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict):
            cfg.update(d)
    except Exception:
        pass
    _sane_config(cfg)
    if cfg.get("ptt_device") is not None and cfg.get("ptt_button") is not None and "ptt" not in cfg["buttons"]:
        cfg["buttons"]["ptt"] = {"device": cfg["ptt_device"], "guid": None, "index": 0, "button": cfg["ptt_button"]}
    cfg.pop("ptt_device", None)
    cfg.pop("ptt_button", None)
    cfg["openai_api_key"] = (cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
                             or DEFAULT_CONFIG["openai_api_key"] or "").strip()
    model = (cfg.get("openai_model") or os.environ.get("OPENAI_MODEL") or "").strip()
    if not model or model.startswith(RETIRED_OPENAI_MODELS):
        model = DEFAULT_CONFIG["openai_model"]
    cfg["openai_model"] = model
    if cfg.get("ai_provider") not in ("openai", "gemini", "deepseek"):
        cfg["ai_provider"] = "openai"
    for p in ("gemini", "deepseek"):
        cfg[f"{p}_api_key"] = (cfg.get(f"{p}_api_key") or "").strip()
        cfg[f"{p}_model"] = (cfg.get(f"{p}_model") or "").strip() or DEFAULT_CONFIG[f"{p}_model"]
    try:
        ver = int(cfg.get("config_version", 1))
    except (TypeError, ValueError, OverflowError):
        ver = 1
    if ver < 2:
        cfg["auto_start"] = True
        if cfg.get("talk_level") == 0:
            cfg["talk_level"] = 1
        cfg["config_version"] = 2
    if cfg.get("whisper_model") not in {v for _, v in WHISPER_MODELS}:
        cfg["whisper_model"] = DEFAULT_CONFIG["whisper_model"]
    if cfg.get("coach_personality") not in {"apex", "almeida", "mansell", "bentley", "perel", "naujoks"}:
        cfg["coach_personality"] = DEFAULT_CONFIG["coach_personality"]
    return cfg


_CFG_LOCK = threading.RLock()


def save_config(cfg):
    """Saved from the GUI and the wheel-button thread: serialised, and written to a temp file then swapped in,
    so two saves can't interleave and a crash mid-write can't leave a broken config.json."""
    with _CFG_LOCK:
        os.makedirs(APP_DIR, exist_ok=True)
        text = json.dumps(cfg, indent=2)
        tmp = f"{CONFIG_PATH}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, CONFIG_PATH)




@dataclass(slots=True)
class Frame:
    game: str
    track: str
    car: str
    laps_done: int
    pct: float
    speed: float
    throttle: float
    brake: float
    steer: float
    gear: int
    rpm: float
    cur_time: float
    last_time: float
    in_pit: bool
    off_track: bool
    fuel: float = 0.0
    track_len: Optional[float] = None
    tyre_temps: Optional[list] = None
    max_rpm: float = 0.0
    wheel_kmh: Optional[list] = None
    tyre_press: Optional[list] = None
    restart: bool = False
    session: Optional[str] = None
    position: int = 0
    cars: int = 0
    race_laps: int = 0
    time_left: Optional[float] = None
    gap_ahead: Optional[float] = None
    gap_behind: Optional[float] = None
    fuel_cap: float = 0.0
    tyre_wear: Optional[list] = None
    damage: Optional[float] = None
    damage_parts: Optional[list] = None
    rain: Optional[float] = None
    pos: Optional[tuple] = None
    others: Optional[list] = None
    right: Optional[tuple] = None
    race_over: bool = False
    car_ahead: Optional[dict] = None
    car_behind: Optional[dict] = None
    others_meta: Optional[list] = None
    tyre_wear_frac: bool = False
    lap_invalid: bool = False
    flag: Optional[str] = None
    rain_in_10: Optional[float] = None
    rain_in_30: Optional[float] = None
    rain_later: Optional[float] = None
    precip: Optional[float] = None
    water_temp: Optional[float] = None
    oil_temp: Optional[float] = None
    energy: Optional[float] = None
    energy_lap: Optional[float] = None
    track_limits: Optional[int] = None


class Reader:
    name = "?"
    CAP_BLOCKS = ()

    def connected(self) -> bool:
        raise NotImplementedError

    def raw_blocks(self):
        """{name: block} for every shared-memory block this reader has open (for a capture)."""
        out = {}
        for name, attr, idx in self.CAP_BLOCKS:
            x = getattr(self, attr, None)
            if x is not None and idx is not None:
                x = x[idx] if idx < len(x) else None
            if x is not None:
                out[name] = x
        return out

    def load_raw_blocks(self, blocks):
        """The other way round, for replaying a capture: put recorded bytes where the live blocks would be."""
        for name, attr, idx in self.CAP_BLOCKS:
            data = blocks.get(name)
            blk = _RawBlock(data) if data is not None else None
            if idx is None:
                setattr(self, attr, blk)
            else:
                cur = list(getattr(self, attr, None) or [])
                cur += [None] * (idx + 1 - len(cur))
                cur[idx] = blk
                setattr(self, attr, cur)

    def read(self) -> Optional[Frame]:
        raise NotImplementedError

    def close(self) -> None:
        pass


def _wstr(buf, off: int, nchars: int) -> str:
    return bytes(buf[off:off + nchars * 2]).decode("utf-16-le", "ignore").split("\x00")[0].strip()


_U_f = struct.Struct("<f").unpack_from
_U_d = struct.Struct("<d").unpack_from
_U_i = struct.Struct("<i").unpack_from
_U_I = struct.Struct("<I").unpack_from
_U_H = struct.Struct("<H").unpack_from
_U_h = struct.Struct("<h").unpack_from
_U_b = struct.Struct("<b").unpack_from
_U_2i = struct.Struct("<2i").unpack_from
_U_2f = struct.Struct("<2f").unpack_from
_U_3f = struct.Struct("<3f").unpack_from
_U_4f = struct.Struct("<4f").unpack_from
_U_5f = struct.Struct("<5f").unpack_from
_U_4i = struct.Struct("<4i").unpack_from
_U_3d = struct.Struct("<3d").unpack_from
_U_3h = struct.Struct("<3h").unpack_from
_U_II = struct.Struct("<II").unpack_from
_U_Hfff = struct.Struct("<Hfff").unpack_from
_U_F1_HDR = struct.Struct("<HBBBBB").unpack_from
_ZERO8 = bytes(8)
_U_DR2 = struct.Struct("<66f").unpack_from


class ACReader(Reader):
    """Assetto Corsa, ACC and AC Rally share the acpmf_* shared-memory layout for every field used here."""
    CAP_BLOCKS = (("physics", "m", 0), ("graphics", "m", 1), ("static", "m", 2), ("crewchief", "ccx", None),
                  ("cspweather", "cspw", None))
    name = "AC / ACC / AC Rally"
    GAMES = (("acs.exe", "AC"), ("acs_x86", "AC"), ("ac2-win64", "ACC"), ("acr.exe", "AC Rally"), ("acr-win64", "AC Rally"))

    def __init__(self):
        self.m = None
        self._cur_game = None
        self._proc_snap = None
        self.ccx, self._ccx_retry = None, 0.0
        self.cspw, self._cspw_retry = None, 0.0
        self._cspw_seq, self._cspw_seen, self._cspw_seg, self._cspw_hist = None, 0.0, None, deque(maxlen=240)
        self._cspw_ok = False
        self._chk_lap = None
        self._laps_seen, self._laps_changed = None, -99.0
        self._static = None
        self._acc_v = {}
        self._wcal = _WheelCal()
        self._pl_fast, self._pl_off = None, False
        self._vl_seen = False

    def _game(self):
        _PROCS.ensure()
        snap = _PROCS.state[0]
        if snap is self._proc_snap:
            return self._cur_game
        self._proc_snap = snap
        for exe, label in self.GAMES:
            if running(exe):
                self._cur_game = label
                return label
        self._cur_game = None
        return None

    def close(self):
        self._chk_lap, self._laps_seen, self._laps_changed = None, None, -99.0
        self._static = None
        self._acc_v = {}
        if self.m:
            for x in self.m:
                if x:
                    x.close()
            self.m = None
        if getattr(self, "ccx", None) is not None:
            self.ccx.close()
            self.ccx = None
        self._cspw_seq, self._cspw_seen, self._cspw_seg, self._cspw_ok = None, 0.0, None, False
        self._cspw_hist.clear()
        if getattr(self, "cspw", None) is not None:
            self.cspw.close()
            self.cspw = None

    def connected(self) -> bool:
        if self._game() is None:
            self.close()
            return False
        if self.m is None:
            parts = [SharedMem.open(f"Local\\acpmf_{n}") for n in ("physics", "graphics", "static")]
            if not all(parts):
                for x in parts:
                    if x:
                        x.close()
                return False
            self.m = parts
        return _i(self.m[1][0:12], 4) in (2, 3)

    def read(self) -> Optional[Frame]:
        p, g, s = self.m[0][0:800], self.m[1][0:1600], self.m[2][0:1200]
        if _i(g, 4) != 2:
            return None
        st = self._static
        if st is None or st[0] != s:
            self._chk_lap = self._laps_seen = None
            self._acc_v.clear()
            self._wcal.reset()
            self._pl_fast, self._pl_off, self._vl_seen = None, False, False
            radius = _U_4f(s, 436)
            st = self._static = (s, _wstr(s, 134, 33), _wstr(s, 68, 33), _f(s, 520), radius, _i(s, 412),
                                 all(0.15 < r < 0.6 for r in radius), max(0, _i(s, 64)), max(0.0, _f(s, 416)),
                                 _wstr(s, 524, 33).strip())
        _s, track, car_name, spline, radius, max_rpm, radius_ok, n_cars, max_fuel, layout = st
        if not track:
            return None
        game = self._cur_game or self._game() or "AC"
        if layout and game != "ACC" and layout.lower() not in track.lower():
            track = f"{track} ({layout})"
        gas, brake, fuel = _U_3f(p, 4)
        gear, rpm = _U_2i(p, 16)
        steer, speed = _U_2f(p, 24)
        temps = list(_U_4f(p, 152))
        temps = [t - 273.15 if t > 200 else t for t in temps]
        press = list(_U_4f(p, 88))
        omega = _U_4f(p, 104)
        wheel_kmh = ([abs(w) * r * 3.6 for w, r in zip(omega, radius)] if radius_ok
                     else self._wcal.update(speed, gas, brake, omega))
        tyres_out = _i(p, 244)
        laps_done, _pos, i_cur, i_last = _U_4i(g, 132)
        laps_done, _pos = max(0, laps_done), max(0, _pos)
        in_pit = _i(g, 160) != 0
        if game == "ACC" and not self._pl_off:
            pl = _i(g, 1236)
            if pl == 1 and speed > 130.0:
                t_m = time.monotonic()
                if self._pl_fast is None:
                    self._pl_fast = t_m
                elif t_m - self._pl_fast > 3.0:
                    self._pl_off = True
                in_pit = True
            elif pl in (0, 1):
                self._pl_fast = None
                in_pit = in_pit or pl == 1
        pct = _f(g, 248)
        fr = Frame(game, track, car_name, laps_done, max(0.0, min(0.99999, pct)),
                   speed, gas, brake, steer, gear - 1, float(rpm), i_cur / 1000.0, max(0, i_last) / 1000.0,
                   in_pit, tyres_out > 2, fuel, spline if 500 < spline < 40000 else None,
                   temps if any(t > 1 for t in temps) else None, float(max_rpm),
                   wheel_kmh, press if any(x > 5 for x in press) else None)
        if game != "AC Rally":
            fr.session = {0: "practice", 1: "qualifying", 2: "race", 3: "practice", 4: "practice", 7: "practice",
                          8: "qualifying"}.get(_i(g, 8))
            fr.position, fr.cars = _pos, n_cars
            laps = _i(g, 172)
            fr.race_laps = laps if 0 < laps < 1000 else 0
            tl = _f(g, 152) / 1000.0
            fr.time_left = tl if 0 < tl < 86400 and not fr.race_laps else None
            flag = _i(g, 1224 if game == "ACC" else 268)
            fr.flag = {1: "blue", 2: "yellow"}.get(flag)
            now_m = time.monotonic()
            if laps_done != self._laps_seen:
                if self._laps_seen is not None:
                    if laps_done > self._laps_seen:
                        self._laps_changed = now_m
                    else:
                        self._chk_lap = None
                self._laps_seen = laps_done
            if flag == 5 and fr.session == "race":
                if self._chk_lap is None:
                    took_it = now_m - self._laps_changed < (0.4 if _pos == 1 else 0.12)
                    self._chk_lap = laps_done - 1 if took_it else laps_done
            elif fr.session != "race" or laps_done == 0:
                self._chk_lap = None
            fr.race_over = bool(fr.session == "race" and (
                (self._chk_lap is not None and laps_done > self._chk_lap)
                or (fr.race_laps > 0 and laps_done >= fr.race_laps)))
            fr.fuel_cap = max_fuel
            fr.damage_parts = list(_U_5f(p, 224))
            if game == "ACC":
                self._acc_race(fr, g)
                w = _f(p, 712)
                fr.water_temp = w if 20.0 < w < 200.0 else None
                valid = _i(g, 1408)
                if valid == 1:
                    self._vl_seen = True
                elif valid == 0 and self._vl_seen:
                    fr.lap_invalid = True
                self._acc_cars(fr, g, speed)
            else:
                if game == "AC":
                    self._csp_weather(fr)
                self._crewchief(fr, _i(g, 148), i_last)
        return fr

    _CSP_RAIN = {0: 0.1, 1: 0.2, 2: 0.4, 3: 0.05, 4: 0.15, 5: 0.25, 6: 0.3, 7: 0.6, 8: 1.0, 12: 0.2, 13: 0.5, 14: 0.8,
                 27: 0.3, 28: 0.5, 32: 0.5}

    def _csp_weather(self, fr):
        """Original AC has no weather of its own: with Custom Shaders Patch it's whatever the WeatherFX runs (Pure and
        Pure Planner, Sol...). The SimCoach Weather Link app (apps/lua/SimCoachWeather, installed by SimCoach) shares
        it as Local\\SimCoach.CSPWeather.v1, 64 bytes, natural alignment: version @0, seq @4 (odd mid-write),
        currentType @8, upcomingType @12 (ac.WeatherType), transition @16, rainIntensity @20, rainWetness @24,
        rainWater @28, ambient @32, road temp @36, roadGrip @40, time multiplier @44, weatherFX @48, CSP build @52,
        time of day @56 (double). Rain and track: fr.rain; what's next (Pure Planner's next weather, timed from how
        fast the blend into it moves): rain_in_10 / rain_in_30, or rain_later when it hasn't started yet."""
        now = time.monotonic()
        w = self.cspw
        if w is None:
            if now < self._cspw_retry:
                return
            self._cspw_retry = now + 5.0
            w = self.cspw = SharedMem.open(CSP_WEATHER_MMF)
            if w is None:
                return
        raw = w[0:64]
        ver, seq, cur, nxt = _U_4i(raw, 0)
        if ver != 1 or seq & 1 or _i(w[0:8], 4) != seq:
            return
        if seq != self._cspw_seq:
            self._cspw_seq, self._cspw_seen = seq, now
        elif now - self._cspw_seen > 3.0:
            return
        trans, rain, wet, water = _U_4f(raw, 16)
        if not all(0.0 <= x <= 2.0 for x in (trans, rain, wet, water)):
            return
        if not self._cspw_ok:
            self._cspw_ok = True
            file_log(f"AC weather from CSP / Pure: connected (CSP build {_i(raw, 52)}, WeatherFX {'on' if _i(raw, 48) else 'off'})")
        track = max(water, 0.3 * wet)
        fr.rain = max(min(rain, 1.0), track if track >= 0.15 else 0.0)
        fr.precip = min(rain, 1.0)
        hist = self._cspw_hist
        if (cur, nxt) != self._cspw_seg or (hist and trans < hist[-1][1] - 0.05):
            self._cspw_seg = (cur, nxt)
            hist.clear()
        if not hist or now - hist[-1][0] >= 1.0:
            hist.append((now, trans))
        while hist and now - hist[0][0] > 60.0:
            hist.popleft()
        rate = None
        if len(hist) >= 2:
            k = 0
            while k + 1 < len(hist) and hist[k + 1][1] <= hist[0][1] + 1e-6:
                k += 1
            if hist[-1][0] - hist[k][0] >= 5.0 or (k == 0 and hist[-1][0] - hist[0][0] >= 10.0):
                rate = (hist[-1][1] - hist[k][1]) / (hist[-1][0] - hist[k][0])
        r_now, r_next = max(rain, self._CSP_RAIN.get(cur, 0.0)), self._CSP_RAIN.get(nxt, 0.0)
        soon = later = eventually = 0.0
        if r_next >= r_now + 0.05:
            onset = max(0.02, (0.05 - r_now) / (r_next - r_now))
            if trans >= onset:
                soon = later = r_next
            elif rate is not None and rate > 1e-5:
                eta = (onset - trans) / rate
                if eta <= 600:
                    soon = later = r_next
                elif eta <= 1800:
                    later = r_next
                else:
                    eventually = r_next
            else:
                eventually = r_next
        fr.rain_in_10, fr.rain_in_30, fr.rain_later = soon, later, eventually

    _ACC_RAIN = (0.0, 0.1, 0.3, 0.55, 0.8, 1.0)
    _ACC_GRIP_WET = (0.0, 0.0, 0.0, 0.0, 0.04, 0.45, 0.8)

    def _acc_race(self, fr, g):
        """ACC graphics page, after isValidLap (field order as in Kunos' SPageFileGraphic, pack 4): trackGripStatus
        @1556, rainIntensity @1560, rainIntensityIn10min @1564, rainIntensityIn30min @1568, gapAhead/gapBehind @1580/
        @1584 (milliseconds)."""
        grip, rain, r10, r30 = _U_4i(g, 1556)
        if 0 <= rain <= 5 and 0 <= grip <= 6:
            fr.rain = max(self._ACC_RAIN[rain], self._ACC_GRIP_WET[grip])
            fr.precip = self._ACC_RAIN[rain]
            if 0 <= r10 <= 5:
                fr.rain_in_10 = self._ACC_RAIN[r10]
            if 0 <= r30 <= 5:
                fr.rain_in_30 = self._ACC_RAIN[r30]
        ga, gb = _U_2i(g, 1580)
        if fr.position > 1 and 0 < ga < 600000:
            fr.gap_ahead = ga / 1000.0
        if fr.position >= 1 and 0 < gb < 600000:
            fr.gap_behind = gb / 1000.0

    def _acc_cars(self, fr, g, speed):
        """ACC's graphics page holds every car's world position (no app needed): activeCars @252,
        carCoordinates[60][3] @256, carID[60] @976, playerCarID @1216. Each car's speed comes from how far it moved,
        so a car crawling down the pit lane beside the straight, or parked off the track, isn't called alongside."""
        n = _i(g, 252)
        if not 0 < n <= 60:
            return
        ids = struct.unpack_from(f"<{n}i", g, 976)
        try:
            k_me = ids.index(_i(g, 1216))
        except ValueError:
            return
        xyz = struct.unpack_from(f"<{3 * n}f", g, 256)
        mx, my, mz = fr.pos = xyz[3 * k_me:3 * k_me + 3]
        now = time.monotonic()
        vel = self._acc_v
        floor = 0.6 * speed
        others = []
        for k in range(n):
            if k == k_me:
                continue
            o = 3 * k
            x, y, z = xyz[o:o + 3]
            cid = ids[k]
            prev = vel.get(cid)
            if prev is None or now - prev[0] > 1.0:
                prev = vel[cid] = (now, x, z, None)
            elif now - prev[0] >= 0.2:
                prev = vel[cid] = (now, x, z, math.hypot(x - prev[1], z - prev[2]) / (now - prev[0]) * 3.6)
            if abs(x - mx) <= 10.0 and abs(z - mz) <= 10.0 and (prev[3] is None or prev[3] >= floor):
                others.append((x, y, z))
        fr.others = others

    def _crewchief(self, fr, best_ms, last_ms):
        """Other cars come from the CrewChiefEx AC app (apps/python/CrewChiefEx, on in Content Manager > Settings >
        Assetto Corsa > Python apps): it shares every car's position 40 times a second as 'acpmf_crewchief'.
        Layout from its shared_mem.py (pack 4): numVehicles @0, focusVehicle @4, vehicleInfo[128] @520, 228 bytes
        each: driverName @4 (64B), carModel @68 (64B), lapCount @140, worldPosition @156, isCarInPit @172,
        realtime position (0-based) @180, spline position @184, isConnected @188."""
        now = time.monotonic()
        if self.ccx is None:
            if now < self._ccx_retry:
                return
            self._ccx_retry = now + 5.0
            self.ccx = SharedMem.open("Local\\acpmf_crewchief")
            if self.ccx is None:
                return
        n, me = _U_2i(self.ccx[0:8], 0)
        if not 0 < n <= 128 or not 0 <= me < n:
            return
        blk = self.ccx[520:520 + n * 228]
        cars = []
        for k in range(n):
            o = k * 228
            if not _i(blk, o + 188):
                continue
            cars.append((k, _U_3f(blk, o + 156), _i(blk, o + 140) + _f(blk, o + 184),
                         _i(blk, o + 180), _i(blk, o + 172), o))
        mine = next((c for c in cars if c[0] == me), None)
        if mine is None:
            return
        mx, _my, mz = fr.pos = mine[1]
        others_pos, others_meta = [], []
        for c in cars:
            if c[0] != me and not c[4]:
                cp = c[1]
                ddx, ddz = abs(cp[0] - mx), abs(cp[2] - mz)
                if ddx <= 10.0 and ddz <= 10.0:
                    others_pos.append(cp)
                if ddx <= 25.0 and ddz <= 25.0:
                    co = c[5]
                    others_meta.append({"pos": cp, "name": _cstr(blk, co + 4, 64), "position": c[3] + 1 if c[3] >= 0 else 0,
                                        "car": nice_name(_cstr(blk, co + 68, 64))})
        fr.others = others_pos
        if others_meta:
            fr.others_meta = others_meta
        tlen = fr.track_len or 4000.0
        lap_s = (best_ms if best_ms > 0 else last_ms) / 1000.0
        ahead = next((c for c in cars if c[3] == mine[3] - 1), None) if mine[3] > 0 else None
        behind = next((c for c in cars if c[3] == mine[3] + 1), None) if mine[3] >= 0 else None
        if ahead is not None:
            ao = ahead[5]
            dpct = ahead[2] - mine[2]
            dist_m = dpct * tlen if 0 < dpct < 1 else math.hypot(ahead[1][0] - mx, ahead[1][2] - mz)
            if lap_s > 10 and 0 < dpct < 1:
                fr.gap_ahead = dpct * lap_s
            fr.car_ahead = {"name": _cstr(blk, ao + 4, 64), "position": ahead[3] + 1,
                            "car": nice_name(_cstr(blk, ao + 68, 64)),
                            "distance_m": round(max(1.0, dist_m)), "gap_s": fr.gap_ahead}
        if behind is not None:
            bo = behind[5]
            dpct = mine[2] - behind[2]
            dist_m = dpct * tlen if 0 < dpct < 1 else math.hypot(behind[1][0] - mx, behind[1][2] - mz)
            if lap_s > 10 and 0 < dpct < 1:
                fr.gap_behind = dpct * lap_s
            fr.car_behind = {"name": _cstr(blk, bo + 4, 64), "position": behind[3] + 1,
                             "car": nice_name(_cstr(blk, bo + 68, 64)),
                             "distance_m": round(max(1.0, dist_m)), "gap_s": fr.gap_behind}



def _cstr(buf, off, n):
    return bytes(buf[off:off + n]).split(b"\x00")[0].decode("utf-8", "ignore").strip()


class SharedMem:
    """Read-only view of a game's named shared-memory block. Opens existing blocks only (never creates
    them) and maps the whole block, so it works whatever size the game made it."""

    def __init__(self, ptr, size, handle, k32):
        self.ptr, self.size, self.handle, self.k32 = ptr, size, handle, k32
        try:
            self.view = memoryview((ctypes.c_ubyte * size).from_address(ptr)).cast("B")
        except Exception:
            self.view = None

    _k32 = None
    _MBI = None

    @classmethod
    def open(cls, name):
        if sys.platform != "win32" or ctypes is None:
            return None
        if cls._k32 is None:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenFileMappingW.restype = wintypes.HANDLE
            k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
            k32.MapViewOfFile.restype = ctypes.c_void_p
            k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
            k32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
            k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]

            class MBI(ctypes.Structure):
                _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                            ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
                            ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                            ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]
            cls._k32, cls._MBI = k32, MBI
        k32 = cls._k32
        h = k32.OpenFileMappingW(0x0004, False, name)
        if not h:
            return None
        p = k32.MapViewOfFile(h, 0x0004, 0, 0, 0)
        if not p:
            k32.CloseHandle(h)
            return None
        mbi = cls._MBI()
        k32.VirtualQuery(p, ctypes.byref(mbi), ctypes.sizeof(mbi))
        return cls(p, int(mbi.RegionSize), h, k32)

    def __getitem__(self, key):
        if isinstance(key, slice):
            a = key.start or 0
            b = self.size if key.stop is None else key.stop
            n = max(0, min(b, self.size) - a)
            data = ctypes.string_at(self.ptr + a, n) if n else b""
            return data if len(data) == b - a else data + bytes(max(0, (b - a) - len(data)))
        if 0 <= key < self.size:
            return ctypes.string_at(self.ptr + key, 1)[0]
        return 0

    def close(self):
        self.view = None
        try:
            self.k32.UnmapViewOfFile(self.ptr)
            self.k32.CloseHandle(self.handle)
        except Exception:
            pass


class _RawBlock:
    """Recorded bytes standing in for a SharedMem block (replaying a capture): same slicing rules."""

    def __init__(self, data):
        self.data = bytes(data)
        self.size = len(self.data)
        self.view = memoryview(self.data)

    def __getitem__(self, key):
        if isinstance(key, slice):
            a = key.start or 0
            b = self.size if key.stop is None else key.stop
            d = self.data[a:b]
            return d if len(d) == b - a else d + bytes(max(0, (b - a) - len(d)))
        return self.data[key] if 0 <= key < self.size else 0

    def __len__(self):
        return self.size

    def close(self):
        pass


def _span(m, a, n):
    """m[a:a+n] without a copy when the mapping covers it: a live view for arrays of other cars, read once and
    dropped within the same read() (the player's own records are still snapshot copies). Plain bytes (tests)
    give a zero-copy view too; a short block falls back to the zero-padded copy."""
    v = getattr(m, "view", None)
    if v is None and isinstance(m, (bytes, bytearray)):
        v = memoryview(m)
    if v is not None and a + n <= len(v):
        return v[a:a + n]
    return memoryview(m[a:a + n])



CSP_WEATHER_MMF = "Local\\SimCoach.CSPWeather.v1"
CSP_WEATHER_APP_DIR = "SimCoachWeather"
CSP_WEATHER_MANIFEST = r"""[ABOUT]
NAME = SimCoach Weather Link
AUTHOR = SimCoach
VERSION = 1.0
DESCRIPTION = Shares the CSP / Pure weather (rain, track wetness, puddles, what's coming next) with SimCoach. Runs by itself.

[CORE]
LAZY = NONE

[WINDOW_...]
ID = main
NAME = SimCoach Weather Link
ICON = icon.png
FUNCTION_MAIN = windowMain
SIZE = 360, 110
"""
CSP_WEATHER_LUA = r"""-- SimCoach Weather Link, a Lua app for Custom Shaders Patch.
-- Shares the weather CSP is running (Pure and Pure Planner, or any other WeatherFX) with SimCoach, the voice
-- coach: rain, how wet the track is, puddles, and what's coming next. It only reads, it changes nothing in the
-- game, and it runs by itself from the start (LAZY = NONE); the window is only there to check it's working.

local VERSION = 1
local MMF_NAME = 'SimCoach.CSPWeather.v1'     -- SimCoach opens it as Local\SimCoach.CSPWeather.v1
local LAYOUT = [[
  int32_t version;
  int32_t seq;
  int32_t currentType;
  int32_t upcomingType;
  float transition;
  float rainIntensity;
  float rainWetness;
  float rainWater;
  float ambientTemperature;
  float roadTemperature;
  float roadGrip;
  float timeMultiplier;
  int32_t weatherFX;
  int32_t cspVersion;
  double timeOfDay;
]]

local mem, seq, status = nil, 0, 'Starting...'
local retryAt = 0
local setupMem, lastSetupSeq, setupRetryAt = nil, 0, 0

local function num(v, fallback)
  v = tonumber(v)
  if v == nil or v ~= v or v == math.huge or v == -math.huge then return fallback end
  return v
end

local cspVersion = 0
if ac.getPatchVersionCode then cspVersion = num(ac.getPatchVersionCode(), 0) end

local function open(t)
  if t < retryAt then return end
  retryAt = t + 5
  local ok, m = pcall(ac.writeMemoryMappedFile, MMF_NAME, LAYOUT)
  if ok and m ~= nil then
    mem, status = m, 'Sharing the weather with SimCoach'
  else
    status = 'Could not share the weather: ' .. tostring(m)
  end
end

local clock = 0

function script.update(dt)
  clock = clock + (num(dt, 0))
  if mem == nil then
    open(clock)
    if mem == nil then return end
  end
  local sim = ac.getSim()
  local c = sim.weatherConditions
  seq = seq + 1                                -- odd while writing, even once a full set is in
  mem.seq = seq
  mem.version = VERSION
  if c ~= nil then
    mem.currentType = num(c.currentType, -1)
    mem.upcomingType = num(c.upcomingType, -1)
    mem.transition = num(c.transition, 0)
  else
    mem.currentType, mem.upcomingType, mem.transition = -1, -1, 0
  end
  mem.rainIntensity = num(sim.rainIntensity, 0)
  mem.rainWetness = num(sim.rainWetness, 0)
  mem.rainWater = num(sim.rainWater, 0)
  mem.ambientTemperature = num(sim.ambientTemperature, 0)
  mem.roadTemperature = num(sim.roadTemperature, 0)
  mem.roadGrip = num(sim.roadGrip, 0)
  mem.timeMultiplier = num(sim.timeMultiplier, 1)
  mem.weatherFX = sim.isWeatherFXActive and 1 or 0
  mem.cspVersion = cspVersion
  mem.timeOfDay = num(sim.timeTotalSeconds, 0)
  seq = seq + 1
  mem.seq = seq
  if setupMem == nil and ac.readMemoryMappedFile and clock >= setupRetryAt then
    setupRetryAt = clock + 2
    local ok_s, sm = pcall(ac.readMemoryMappedFile, 'SimCoach.CSPSetup.v1', [[
      int32_t version; int32_t seq; float fuel; int32_t tyreCompound;
      float pressLF; float pressRF; float pressLR; float pressRR;
      float brakeBias; int32_t wing; int32_t arbFront; int32_t arbRear; int32_t tc; int32_t abs;
    ]])
    if ok_s and sm ~= nil then setupMem = sm end
  end
  if setupMem ~= nil and setupMem.version == 1 and setupMem.seq > 0 and setupMem.seq % 2 == 0 and setupMem.seq ~= lastSetupSeq then
    lastSetupSeq = setupMem.seq
    if ac.setBrakeBias then pcall(ac.setBrakeBias, setupMem.brakeBias / 100.0) end
    if ac.setTC then pcall(ac.setTC, setupMem.tc) end
    if ac.setABS then pcall(ac.setABS, setupMem.abs) end
    if physics and physics.setCarFuel then pcall(physics.setCarFuel, 0, setupMem.fuel) end
  end
end

local NAMES = { [0] = 'Light thunderstorm', 'Thunderstorm', 'Heavy thunderstorm', 'Light drizzle', 'Drizzle',
  'Heavy drizzle', 'Light rain', 'Rain', 'Heavy rain', 'Light snow', 'Snow', 'Heavy snow', 'Light sleet', 'Sleet',
  'Heavy sleet', 'Clear', 'Few clouds', 'Scattered clouds', 'Broken clouds', 'Overcast', 'Fog', 'Mist', 'Smoke',
  'Haze', 'Sand', 'Dust', 'Squalls', 'Tornado', 'Hurricane', 'Cold', 'Hot', 'Windy', 'Hail' }

local function name(t)
  return NAMES[num(t, -1)] or '?'
end

function script.windowMain(dt)
  local sim = ac.getSim()
  ui.text(status)
  ui.text(string.format('Rain %.2f   Wetness %.2f   Puddles %.2f', num(sim.rainIntensity, 0),
    num(sim.rainWetness, 0), num(sim.rainWater, 0)))
  local c = sim.weatherConditions
  if c ~= nil then
    ui.text(string.format('Now: %s   Next: %s (%d%%)', name(c.currentType), name(c.upcomingType),
      math.floor(num(c.transition, 0) * 100 + 0.5)))
  end
  ui.text(sim.isWeatherFXActive and 'Weather: CSP WeatherFX (Pure, Sol...)' or 'Weather: no WeatherFX, so no rain')
end
"""
CSP_WEATHER_ICON = """
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
/wAEgKDs1BrzMgAAAABJRU5ErkJggg==
"""


def find_ac_dir(steam_dirs=None):
    """Assetto Corsa's folder (Steam app 244210): every Steam library in libraryfolders.vdf, then the usual places."""
    steams = list(steam_dirs or [])
    if sys.platform == "win32" and steam_dirs is None:
        try:
            import winreg
            for hive, key, val in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        steams.append(str(winreg.QueryValueEx(k, val)[0]))
                except OSError:
                    pass
        except Exception:
            pass
    if steam_dirs is None:
        steams += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    libs = []
    for steam in steams:
        steam = os.path.normpath(steam)
        libs.append(steam)
        try:
            with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="ignore") as fh:
                libs += [m.group(1).replace("\\\\", "\\") for m in re.finditer(r'"path"\s+"([^"]+)"', fh.read())]
        except OSError:
            pass
    seen = set()
    for lib in libs:
        d = os.path.join(lib, "steamapps", "common", "assettocorsa")
        if d.lower() in seen:
            continue
        seen.add(d.lower())
        if os.path.isfile(os.path.join(d, "acs.exe")):
            return d
    return None


def install_csp_weather_app(log=print, ac_dir=None):
    """Put the SimCoach Weather Link into <AC>/apps/lua (only when CSP is installed), or bring it up to date.
    Only ever writes inside its own folder. Returns the folder, or None."""
    import base64
    ac_dir = ac_dir or find_ac_dir()
    if not ac_dir or not os.path.isdir(os.path.join(ac_dir, "extension")):
        return None
    dst = os.path.join(ac_dir, "apps", "lua", CSP_WEATHER_APP_DIR)
    files = {"manifest.ini": CSP_WEATHER_MANIFEST.encode("utf-8"), "SimCoachWeather.lua": CSP_WEATHER_LUA.encode("utf-8"),
             "icon.png": base64.b64decode("".join(CSP_WEATHER_ICON.split()))}
    changed = []
    try:
        os.makedirs(dst, exist_ok=True)
        for name, data in files.items():
            path = os.path.join(dst, name)
            try:
                with open(path, "rb") as fh:
                    if fh.read() == data:
                        continue
            except OSError:
                pass
            tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.new"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
            changed.append(name)
    except OSError as e:
        log(f"Couldn't install the AC weather link (CSP/Pure) in {dst}: {e}")
        return None
    if changed:
        log(f"AC weather link for CSP/Pure installed in {dst}"
            + (" (restart Assetto Corsa to load it)" if running("acs.exe", "acs_x86") else ""))
    return dst


class _ProcScanner:
    """Keeps the list of running .exe names fresh in the background so the telemetry loop never stalls."""

    def __init__(self):
        self.state = (frozenset(), {})
        self._started = False
        self._lock = threading.Lock()

    @property
    def names(self):
        return self.state[0]

    def _scan(self):
        try:
            import psutil
            new_names = frozenset((p.info["name"] or "").lower() for p in psutil.process_iter(["name"]))
            if new_names != self.state[0]:
                self.state = (new_names, {})
        except Exception:
            pass

    def ensure(self):
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            self._started = True
        self._scan()

        def loop():
            while True:
                time.sleep(2)
                self._scan()
        threading.Thread(target=loop, daemon=True, name="proc-scan").start()


_PROCS = _ProcScanner()


def running(*names):
    """True if a running process's exe name contains any of `names`."""
    _PROCS.ensure()
    current, cache = _PROCS.state
    hit = cache.get(names)
    if hit is not None:
        return hit
    res = any(n.lower() in pn for n in names for pn in current)
    cache[names] = res
    return res


def _f(b, o, _u=_U_f):
    return _u(b, o)[0]


def _d(b, o, _u=_U_d):
    return _u(b, o)[0]


def _i(b, o, _u=_U_i):
    return _u(b, o)[0]


class _WheelCal:
    """Wheel surface speeds for sims that publish how fast each wheel spins but no usable tyre radius (ACC leaves
    tyreRadius empty, AMS2 has none, encrypted rF2/LMU cars can send 0): each wheel's km/h-per-spin factor is learnt
    while the car rolls freely (60-300 km/h, off the brake, part throttle) as the median of speed / spin. Units cancel,
    so rad/s or rev/s both work. Until ~1 s of such driving has been seen there are no wheel speeds (no lock-up calls)."""
    N, MIN = 150, 60

    def __init__(self):
        self.reset()

    def reset(self):
        self.samples = ([], [], [], [])
        self.k = None
        self._n = 0

    def update(self, spd, thr, brk, spins):
        if 60.0 < spd < 300.0 and brk < 0.02 and thr < 0.6:
            for lst, w in zip(self.samples, spins):
                a = abs(w)
                if a > 1e-3:
                    lst.append(spd / a)
                    if len(lst) > self.N:
                        del lst[0]
            self._n += 1
            if self._n % 15 == 0 and all(len(lst) >= self.MIN for lst in self.samples):
                ks = [sorted(lst)[len(lst) // 2] for lst in self.samples]
                fr_ratio, rr_ratio = ks[0] / ks[1], ks[2] / ks[3]
                if 0.9 < fr_ratio < 1.1 and 0.9 < rr_ratio < 1.1:
                    self.k = ks
        k = self.k
        return [abs(w) * kk for w, kk in zip(spins, k)] if k else None



class ACEvoReader(Reader):
    name = "AC EVO"
    CAP_BLOCKS = (("physics", "m", 0), ("graphics", "m", 1), ("static", "m", 2))

    def __init__(self):
        self.m = None

    def close(self):
        if self.m:
            for x in self.m:
                if x:
                    x.close()
            self.m = None

    def _open(self):
        if self.m is None and running("assettocorsaevo"):
            parts = [
                SharedMem.open("Local\\acevo_pmf_physics"),
                SharedMem.open("Local\\acevo_pmf_graphics"),
                SharedMem.open("Local\\acevo_pmf_static"),
            ]
            if all(parts):
                self.m = tuple(parts)
            else:
                for x in parts:
                    if x:
                        x.close()
        return self.m

    def connected(self):
        if not running("assettocorsaevo"):
            self.close()
            return False
        return self._open() is not None

    def read(self):
        p, g, st = self.m[0][0:800], self.m[1][0:4900], self.m[2][0:208]
        if _i(g, 4) != 2 or not _cstr(st, 136, 33):
            return None
        tl = _f(st, 204)
        temps = list(_U_4f(p, 152))
        temps = [t - 273.15 if t > 200 else t for t in temps]
        press = list(_U_4f(p, 88))
        return Frame("AC EVO", _cstr(st, 136, 33), _cstr(g, 3086, 33), _i(g, 2384),
                     max(0.0, min(0.99999, _f(g, 1244))), _f(p, 28), _f(p, 4), _f(p, 8), _f(p, 24),
                     _i(p, 16) - 1, float(_i(p, 20)), _i(g, 188) / 1000.0, max(0, _i(g, 2396)) / 1000.0,
                     bool(g[3120]), False, _f(p, 12), tl if 500 < tl < 40000 else None,
                     temps if any(t > 1 for t in temps) else None, 0.0, None,
                     press if any(x > 5 for x in press) else None, lap_invalid=not bool(g[3121]))



class _RF2Family(Reader):
    """LMU and rFactor 2 share Studio 397's TelemInfoV01 / VehicleScoringInfoV01 records."""

    @staticmethod
    def _race_state(fr, sc_info, veh, tel, vehicles, telems):
        """ScoringInfoV01 / VehicleScoringInfoV01 / TelemInfoV01 fields (offsets from InternalsPlugin.hpp, pack 4).
        rF2 world space is left-handed with +y up."""
        ses = _i(sc_info, 64)
        fr.session = "practice" if 0 <= ses <= 4 or ses == 9 else "qualifying" if 5 <= ses <= 8 else \
            "race" if 10 <= ses <= 13 else None
        end_et, cur_et, max_laps = _d(sc_info, 76), _d(sc_info, 68), _i(sc_info, 84)
        fr.race_laps = max_laps if 0 < max_laps < 1000 else 0
        fr.time_left = end_et - cur_et if end_et > 0 and not fr.race_laps and end_et - cur_et > 0 else None
        my_plc = max(0, _U_b(veh, 199)[0])
        fr.position, fr.cars = my_plc, max(0, _i(sc_info, 104))
        finish_st = _U_b(veh, 103)[0]
        game_phase = sc_info[108]
        fr.race_over = bool(fr.session == "race" and (
            finish_st == 1 or game_phase == 8 or (fr.race_laps > 0 and fr.laps_done >= fr.race_laps)
        ))
        my_dist = _d(veh, 104)
        lap_len = fr.track_len or _d(sc_info, 88) or 4000.0
        if my_plc > 1 and _i(veh, 240) == 0:
            ga = _d(veh, 232)
            fr.gap_ahead = ga if 0 < ga < 600 else None
        ahead_v = behind_v = None
        for v in vehicles:
            plc = _U_b(v, 199)[0]
            if plc == my_plc - 1 and my_plc > 1:
                ahead_v = v
            elif plc == my_plc + 1 and my_plc >= 1:
                behind_v = v
                if _i(v, 240) == 0:
                    gb = _d(v, 232)
                    fr.gap_behind = gb if 0 < gb < 600 else None
        if ahead_v is not None:
            adist = (_d(ahead_v, 104) - my_dist) % lap_len if lap_len > 0 else 0.0
            if adist <= 0 and fr.gap_ahead:
                adist = fr.gap_ahead * max(fr.speed, 60.0) / 3.6
            fr.car_ahead = {"name": _cstr(ahead_v, 4, 32), "position": int(ahead_v[199]),
                            "car": nice_name(_cstr(ahead_v, 36, 64)),
                            "distance_m": round(max(1.0, adist)), "gap_s": fr.gap_ahead}
        if behind_v is not None:
            bdist = (my_dist - _d(behind_v, 104)) % lap_len if lap_len > 0 else 0.0
            if bdist <= 0 and fr.gap_behind:
                bdist = fr.gap_behind * max(fr.speed, 60.0) / 3.6
            fr.car_behind = {"name": _cstr(behind_v, 4, 32), "position": int(behind_v[199]),
                             "car": nice_name(_cstr(behind_v, 36, 64)),
                             "distance_m": round(max(1.0, bdist)), "gap_s": fr.gap_behind}
        fr.fuel_cap = _d(tel, 608)
        wear = [_d(tel, 848 + w * 260 + 152) for w in range(4)]
        fr.tyre_wear = wear if all(0.0 <= x <= 1.0 for x in wear) else None
        fr.tyre_wear_frac = True
        fr.damage = min(1.0, sum(tel[544:552]) / 8.0)
        water, oil = _d(tel, 364), _d(tel, 372)
        fr.water_temp = water if 1.0 < water < 250.0 else None
        fr.oil_temp = oil if 1.0 < oil < 250.0 else None
        rain, wet = _d(sc_info, 220), _d(sc_info, 332)
        if 0.0 <= rain <= 1.0 and 0.0 <= wet <= 1.0:
            fr.rain = max(rain, wet if wet >= 0.15 else 0.0)
            fr.precip = rain
        mx, _my, mz = fr.pos = _U_3d(tel, 160)
        me = _i(tel, 0)
        v_by_id = None
        others_pos, others_meta = [], []
        for t in telems:
            tid = _i(t, 0)
            if tid != me:
                tp = _U_3d(t, 160)
                ddx, ddz = abs(tp[0] - mx), abs(tp[2] - mz)
                if ddx <= 10.0 and ddz <= 10.0:
                    others_pos.append(tp)
                if ddx <= 25.0 and ddz <= 25.0:
                    if v_by_id is None:
                        v_by_id = {_i(v, 0): v for v in vehicles}
                    vv = v_by_id.get(tid)
                    if vv is not None:
                        others_meta.append({"pos": tp, "name": _cstr(vv, 4, 32), "position": max(0, int(_U_b(vv, 199)[0])),
                                            "car": nice_name(_cstr(vv, 36, 64))})
        fr.others = others_pos
        if others_meta:
            fr.others_meta = others_meta
        return fr

    def _paused(self, tel):
        """True when the telemetry clock (TelemInfoV01.mElapsedTime) hasn't moved for half a second: the game is
        paused and the block just holds the last frame (mInRealtime stays set while paused)."""
        et, now = _d(tel, 12), time.monotonic()
        if et != getattr(self, "_et", None):
            self._et, self._et_t = et, now
            return False
        return now - self._et_t > 0.5

    def _vehicle_frame(self, game, sc_info, veh, tel, invalid):
        lap_len = _d(sc_info, 88)
        lapdist = _d(veh, 104)
        vx, vy, vz = _U_3d(tel, 184)
        temps, press, wk, spins = [], [], [], []
        radii_ok = True
        for w in range(4):
            wb = 848 + w * 260
            temps.append(_d(tel, wb + 136) - 273.15)
            press.append(_d(tel, wb + 120) * 0.145038)
            r = tel[wb + 179] / 100.0
            if r <= 0.1:
                radii_ok = False
            spin = _d(tel, wb + 40)
            spins.append(spin)
            wk.append(abs(spin) * r * 3.6 if r > 0.1 else 0.0)
        spd = math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6
        thr, brk = _d(tel, 388), _d(tel, 396)
        if not radii_ok:
            cal = getattr(self, "_wcal", None)
            if cal is None:
                cal = self._wcal = _WheelCal()
            if getattr(self, "_wcal_car", None) != tel[32:96]:
                self._wcal_car = tel[32:96]
                cal.reset()
            wk = cal.update(spd, thr, brk, spins)
        fr = Frame(game, _cstr(sc_info, 0, 64), _cstr(tel, 32, 64), max(0, _U_h(veh, 100)[0]),
                   (lapdist / lap_len) % 1.0 if lap_len > 0 else 0.0, spd,
                   thr, brk, _d(tel, 404), _i(tel, 352), _d(tel, 356),
                   max(0.0, _d(veh, 464)), max(0.0, _d(veh, 168)), bool(veh[198]), False, _d(tel, 524),
                   lap_len if lap_len > 500 else None, temps if all(t > -50 for t in temps) else None,
                   _d(tel, 532), wk, press)
        fr.lap_invalid = invalid
        sec = veh[102]
        local = 0 <= sec <= 2 and sc_info[110 + sec] == 2
        fr.flag = "fcy" if veh[505] else ("yellow" if local else ("blue" if veh[504] == 6 else None))
        return fr


class LMUReader(_RF2Family):
    name = "LMU"
    CAP_BLOCKS = (("LMU_Data", "m", None),)
    SIZE = 324824

    def __init__(self):
        self.m = None
        self.lk, self._lk_retry, self._busy_skips = None, 0.0, 0

    def close(self):
        if self.m:
            self.m.close()
            self.m = None
        if self.lk:
            self.lk.close()
            self.lk = None

    def connected(self):
        if not running("le mans ultimate", "lmu.exe"):
            self.close()
            return False
        if self.m is None:
            self.m = SharedMem.open("LMU_Data")
        return self.m is not None

    def _busy(self):
        """LMU's write lock (LMU_SharedMemoryLockData: LONG waiters, LONG busy) is held while the game copies a new
        frame in. Only peeked at, never taken: a frame read while it's held is skipped (at most 3 in a row)."""
        if self.lk is None:
            now = time.monotonic()
            if now < self._lk_retry:
                return False
            self._lk_retry = now + 5.0
            self.lk = SharedMem.open("LMU_SharedMemoryLockData")
            if self.lk is None:
                return False
        return _i(self.lk[0:8], 4) != 0

    def read(self):
        busy = self._busy()
        if busy and self._busy_skips < 3:
            self._busy_skips += 1
            return None
        if not busy:
            self._busy_skips = 0
        b = self.m
        sc = b[1632:1632 + 548]
        if not sc[115]:
            return None
        hdr = b[128464:128468]
        if not hdr[2]:
            return None
        nt, idx = min(104, hdr[0]), hdr[1]
        if idx >= 104:
            return None
        n = min(104, _i(sc, 104))
        block = _span(b, 2192, n * 584)
        vehicles = [block[i * 584:(i + 1) * 584] for i in range(n)]
        veh = next((v for v in vehicles if v[196]), None)
        if veh is None:
            return None
        veh = bytes(veh)
        tel_off = 128468 + idx * 1888
        tel = b[tel_off:tel_off + 1888]
        t_all = _span(b, 128468, nt * 1888)
        vid = _i(veh, 0)
        if idx >= nt or _i(tel, 0) != vid:
            k = next((i for i in range(nt) if _i(t_all, i * 1888) == vid), None)
            if k is None:
                return None
            tel = b[128468 + k * 1888:128468 + (k + 1) * 1888]
        if self._paused(tel):
            return None
        fr = self._vehicle_frame("LMU", sc, veh, tel, bool(tel[745]))
        telems = [t_all[i * 1888:i * 1888 + 184] for i in range(nt)]
        fr = self._race_state(fr, sc, veh, tel, vehicles, telems)
        self._lmu_extras(fr, tel)
        if not busy and self._busy() and self._busy_skips < 3:
            self._busy_skips += 1
            return None
        self._busy_skips = 0
        return fr


    def _lmu_extras(self, fr, tel):
        """LMU's own additions to TelemInfoV01 (offsets from LMU's InternalsPlugin.hpp): mTrackLimitsSteps @767 (uint8),
        mVirtualEnergy @776 (float). VE comes as a fraction or a percent: once a value above 1.5 has been seen for this
        car it's a percent. A car that has never shown any VE doesn't use it (0 = not this class)."""
        car = tel[32:96]
        if car != getattr(self, "_ve_car", None):
            self._ve_car, self._ve_pct, self._ve_seen = car, False, False
        ve = _f(tel, 776)
        if not (0.0 <= ve <= 105.0):
            ve = None
        elif ve > 1.5:
            self._ve_pct = True
        if ve is not None and self._ve_pct:
            ve /= 100.0
        if ve is not None and ve > 0.002:
            self._ve_seen = True
        if ve is not None and self._ve_seen and ve <= 1.05:
            fr.energy = ve
        fr.track_limits = tel[767]


class RF2Reader(_RF2Family):
    """Needs rFactor2SharedMemoryMapPlugin64 enabled in rF2 (it's installed in Bin64\\Plugins)."""
    name = "rFactor 2"
    CAP_BLOCKS = (("telemetry", "t", None), ("scoring", "s", None))

    def __init__(self):
        self.t = self.s = None
        self._cl_lap, self._cl_ok = None, False

    def close(self):
        for blk in (self.t, self.s):
            if blk:
                blk.close()
        self.t = self.s = None
        self._cl_lap, self._cl_ok = None, False

    def connected(self):
        if not running("rfactor2.exe"):
            self.close()
            return False
        if self.t is None or self.s is None:
            self.close()
            t = SharedMem.open("$rFactor2SMMP_Telemetry$")
            s = SharedMem.open("$rFactor2SMMP_Scoring$")
            if t and s:
                self.t, self.s = t, s
            else:
                if t:
                    t.close()
                if s:
                    s.close()
        return self.t is not None and self.s is not None

    @staticmethod
    def _versions(s, t):
        """The plugin bumps mVersionUpdateBegin before writing a buffer and mVersionUpdateEnd after it's done.
        Both buffers' versions, or None while either one is being written."""
        sb, se = _U_II(s[0:8], 0)
        tb, te = _U_II(t[0:8], 0)
        return (sb, tb) if sb == se and tb == te else None

    def read(self):
        s, t = self.s, self.t
        torn = getattr(self, "_torn", 0)
        v0 = self._versions(s, t)
        if v0 is None and torn < 3:
            self._torn = torn + 1
            return None
        fr = self._read(s, t)
        if v0 is not None and self._versions(s, t) != v0 and torn < 3:
            self._torn = torn + 1
            return None
        self._torn = 0
        return fr

    def _read(self, s, t):
        sc = s[12:12 + 548]
        if not sc[115]:
            return None
        nv = min(128, _i(sc, 104))
        block = _span(s, 560, nv * 584)
        vehicles = [block[i * 584:(i + 1) * 584] for i in range(nv)]
        veh = next((v for v in vehicles if v[196]), None)
        if veh is None:
            return None
        veh = bytes(veh)
        vid = _i(veh, 0)
        cl, lapn = veh[506], _U_h(veh, 100)[0]
        if lapn != self._cl_lap:
            self._cl_lap, self._cl_ok = lapn, False
        if cl == 2:
            self._cl_ok = True
        lap_inv = self._cl_ok and cl < 2
        nt = max(0, min(128, _i(t[12:16], 0)))
        t_block = _span(t, 16, nt * 1888)
        for i in range(nt):
            tb = i * 1888
            if _i(t_block, tb) == vid:
                tel = bytes(t_block[tb:tb + 1888])
                if self._paused(tel):
                    return None
                fr = self._vehicle_frame("rFactor 2", sc, veh, tel, lap_inv)
                telems = [t_block[k * 1888:k * 1888 + 184] for k in range(nt)]
                return self._race_state(fr, sc, veh, tel, vehicles, telems)
        return None



class AMS2Reader(Reader):
    """In AMS2: Options > System > Shared Memory = 'Project CARS 2'."""
    name = "AMS2"
    CAP_BLOCKS = (("pcars2", "m", None),)

    def __init__(self):
        self.m = None
        self._torn = 0
        self._wcal, self._wcal_car = _WheelCal(), None
        self._tl = None
        self._tl_scale = None

    def close(self):
        if self.m:
            self.m.close()
            self.m = None

    def connected(self):
        if not running("ams2"):
            self.close()
            return False
        if self.m is None:
            self.m = SharedMem.open("$pcars2$")
        return self.m is not None

    def _time_left(self, raw, ses, now):
        """mEventTimeRemaining: SharedMemory.h says milliseconds, some builds send seconds. Worked out from how fast
        it counts down (1000 a second = ms); anything over a day can only be ms."""
        if raw <= 0:
            return None
        cal = self._tl
        if cal is None or cal[2] != ses or raw > cal[1] + 5.0:
            self._tl, self._tl_scale = (now, raw, ses), None
        elif self._tl_scale is None and now - cal[0] >= 3.0:
            rate = (cal[1] - raw) / (now - cal[0])
            if rate > 100.0:
                self._tl_scale = 0.001
            elif 0.3 < rate < 3.0:
                self._tl_scale = 1.0
        scale = self._tl_scale or (0.001 if raw > 86400.0 else None)
        return raw * scale if scale else None

    def read(self):
        m = self.m
        s0 = _U_I(m[7320:7324], 0)[0]
        b = m[:20700]
        if (s0 & 1 or _U_I(m[7320:7324], 0)[0] != s0) and self._torn < 3:
            self._torn += 1
            return None
        self._torn = 0
        if _i(b, 8) != 2:
            return None
        idx = _i(b, 20)
        if not 0 <= idx < min(64, _i(b, 24)) or not b[28 + idx * 100]:
            return None
        pb = 28 + idx * 100
        tl = _f(b, 6704)
        track = _cstr(b, 6576, 64)
        var = _cstr(b, 6640, 64)
        temps = list(_U_4f(b, 20600))
        press = list(_U_4f(b, 7372))
        car = _cstr(b, 6444, 64)
        spd, thr, brk = _f(b, 6848) * 3.6, _f(b, 6864), _f(b, 6860)
        if car != self._wcal_car:
            self._wcal_car = car
            self._wcal.reset()
        wk = self._wcal.update(spd, thr, brk, _U_4f(b, 7040))
        fr = Frame("AMS2", f"{track} {var}".strip(), car, _U_I(b, pb + 88)[0],
                   (_f(b, pb + 80) / tl) % 1.0 if tl > 0 else 0.0, spd, thr, brk,
                   _f(b, 6872), _i(b, 6876), _f(b, 6852), max(0.0, _f(b, 6724)), max(0.0, _f(b, 6720)),
                   _U_I(b, 6808)[0] != 0, False, _f(b, 6840) * _f(b, 6844),
                   tl if tl > 500 else None, temps if any(t > 1 for t in temps) else None, _f(b, 6856), wk,
                   press if any(x > 5 for x in press) else None, lap_invalid=bool(b[6712]))
        ses_raw = _i(b, 12)
        race_st = _U_I(b, 16)[0]
        fr.session = {1: "practice", 2: "practice", 3: "qualifying", 4: "race", 5: "race",
                      6: "practice"}.get(ses_raw)
        n = max(0, min(64, _i(b, 24)))
        fr.position, fr.cars = _U_I(b, pb + 84)[0], n
        laps = _U_I(b, 6572)[0]
        fr.race_laps = laps if 0 < laps < 1000 else 0
        fr.race_over = bool(fr.session == "race" and (
            race_st == 3 or (fr.race_laps > 0 and fr.laps_done >= fr.race_laps)
        ))
        tleft = self._time_left(_f(b, 6740), ses_raw, time.monotonic())
        fr.time_left = tleft if tleft is not None and 0 < tleft < 86400 and not fr.race_laps else None
        ga, gb = _f(b, 6728), _f(b, 6732)
        fr.gap_ahead = ga if 0 < ga < 600 else None
        fr.gap_behind = gb if 0 < gb < 600 else None
        fr.fuel_cap = _f(b, 6844)
        wear = list(_U_4f(b, 7136))
        fr.tyre_wear = [x * 100 for x in wear] if all(0 <= x <= 1 for x in wear) else None
        dmg = [_f(b, 7284), _f(b, 7288)] + list(_U_4f(b, 7168))
        fr.damage = max(0.0, min(1.0, max(dmg)))
        fr.rain = max(0.0, min(1.0, _f(b, 7300)))
        oil, water = _f(b, 6820), _f(b, 6828)
        fr.oil_temp = oil if 1.0 < oil < 250.0 else None
        fr.water_temp = water if 1.0 < water < 250.0 else None
        fc = _U_I(b, 6800)[0]
        fr.flag = "blue" if fc == 2 else ("yellow" if fc in (6, 7) else None)
        fr.pos = _U_3f(b, pb + 68)
        my_lap_d = _f(b, pb + 80)
        tlen = tl if tl > 500 else 4000.0
        others_pos, others_meta = [], []
        for k in range(n):
            ob = 28 + k * 100
            if k == idx or not b[ob]:
                continue
            opos = _U_3f(b, ob + 68)
            ddx, ddz = abs(opos[0] - fr.pos[0]), abs(opos[2] - fr.pos[2])
            if ddx <= 10.0 and ddz <= 10.0:
                others_pos.append(opos)
            orace_pos = int(_U_I(b, ob + 84)[0])
            near = ddx <= 25.0 and ddz <= 25.0
            if not (near or (fr.position and orace_pos > 0 and abs(orace_pos - fr.position) == 1)):
                continue
            oname = _cstr(b, ob + 1, 64)
            ocar = nice_name(_cstr(b, 11056 + k * 64, 64)) or nice_name(fr.car)
            if near:
                others_meta.append({"pos": opos, "name": oname, "position": orace_pos, "car": ocar})
            olap_d = _f(b, ob + 80)
            if fr.position > 1 and orace_pos == fr.position - 1:
                dm = (olap_d - my_lap_d) % tlen
                if dm <= 0 or dm > tlen * 0.5:
                    dm = math.hypot(opos[0] - fr.pos[0], opos[2] - fr.pos[2])
                fr.car_ahead = {"name": oname, "position": orace_pos, "car": ocar,
                                "distance_m": round(max(1.0, dm)), "gap_s": fr.gap_ahead}
            elif fr.position >= 1 and orace_pos == fr.position + 1:
                dm = (my_lap_d - olap_d) % tlen
                if dm <= 0 or dm > tlen * 0.5:
                    dm = math.hypot(opos[0] - fr.pos[0], opos[2] - fr.pos[2])
                fr.car_behind = {"name": oname, "position": orace_pos, "car": ocar,
                                 "distance_m": round(max(1.0, dm)), "gap_s": fr.gap_behind}
        fr.others = others_pos
        if others_meta:
            fr.others_meta = others_meta
        return fr



class R3EReader(Reader):
    name = "RaceRoom"
    CAP_BLOCKS = (("r3e", "m", None),)

    def __init__(self):
        self.m = None

    def close(self):
        if self.m:
            self.m.close()
            self.m = None

    def connected(self):
        if not running("rrre"):
            self.close()
            return False
        if self.m is None:
            self.m = SharedMem.open("$R3E")
        return self.m is not None

    def read(self):
        b = self.m[:44024]
        if _i(b, 0) != 3 or _i(b, 20) or _i(b, 24) or _i(b, 28) or _i(b, 780) == -1:
            return None
        tl = _f(b, 736)
        temps = [_f(b, 1744 + w * 24 + 4) for w in range(4)]
        press = [_f(b, 1712 + w * 4) * 0.145038 for w in range(4)]
        track = f"{_cstr(b, 600, 64)} {_cstr(b, 664, 64)}".strip()
        ts = _U_4f(b, 1648)
        wk = [abs(x) * 3.6 for x in ts] if all(x != -1.0 and x == x for x in ts) else None
        fr = Frame("RaceRoom", track, raceroom_car(_i(b, 1196 + 72)), max(0, _i(b, 1028)), max(0.0, _f(b, 1044)) % 1.0,
                   _f(b, 1392) * 3.6, _f(b, 1504), _f(b, 1512), _f(b, 1524), _i(b, 1408),
                   _f(b, 1396) * 60 / (2 * math.pi), max(0.0, _f(b, 1100)), max(0.0, _f(b, 1084)),
                   _i(b, 848) > 0, False, _f(b, 1456), tl if tl > 500 else None,
                   temps if any(t > 1 for t in temps) else None, _f(b, 1400) * 60 / (2 * math.pi), wk,
                   press if any(x > 5 for x in press) else None, lap_invalid=_i(b, 1032) == 0)
        fr.session = {0: "practice", 1: "qualifying", 2: "race", 3: "practice"}.get(_i(b, 780))
        fin_st = _i(b, 996)
        laps = _i(b, 812)
        fr.race_laps = laps if 0 < laps < 1000 else 0
        fr.race_over = bool(fr.session == "race" and (
            fin_st == 1 or (fr.race_laps > 0 and fr.laps_done >= fr.race_laps)
        ))
        tleft = _f(b, 820)
        fr.time_left = tleft if 0 < tleft < 86400 and not fr.race_laps else None
        me, n = max(0, _i(b, 988)), max(0, min(128, _i(b, 2008)))
        fr.position, fr.cars = me, n
        ga, gb = _f(b, 1124), _f(b, 1128)
        fr.gap_ahead = ga if 0 < ga < 600 else None
        fr.gap_behind = gb if 0 < gb < 600 else None
        fr.fuel_cap = _f(b, 1460)
        fr.flag = "yellow" if _i(b, 932) == 1 else ("blue" if _i(b, 964) == 1 else None)
        water, oil = _f(b, 1480), _f(b, 1484)
        fr.water_temp = water if 1.0 < water < 250.0 else None
        fr.oil_temp = oil if 1.0 < oil < 250.0 else None
        ve, ve_cap, ve_lap = _f(b, 1468), _f(b, 1472), _f(b, 1476)
        if ve_cap > 0.0 and 0.0 <= ve <= ve_cap * 1.05:
            fr.energy = ve / ve_cap
            if 0.0 < ve_lap < ve_cap:
                fr.energy_lap = ve_lap / ve_cap
        wear = list(_U_4f(b, 1680))
        fr.tyre_wear = wear if all(0.0 <= x <= 1.0 for x in wear) else None
        fr.tyre_wear_frac = True
        dmg = [x for x in _U_4f(b, 1984) if 0.0 <= x <= 1.0]
        fr.damage = 1.0 - min(dmg) if dmg else None
        fr.pos = _U_3d(b, 56)
        tlen = tl if tl > 500 else 4000.0
        my_d = fr.pct * tlen
        others_pos, others_meta = [], []
        for k in range(n):
            ob = 2012 + k * 328
            plc = _i(b, ob + 132)
            opos = _U_3f(b, ob + 148)
            ddx, ddz = abs(opos[0] - fr.pos[0]), abs(opos[2] - fr.pos[2])
            if (me > 0 and plc == me) or (me == 0 and ddx < 0.5 and ddz < 0.5):
                if _i(b, ob + 128) == 1 and fr.session == "race":
                    fr.race_over = True
                continue
            if ddx <= 10.0 and ddz <= 10.0:
                others_pos.append(opos)
            near = ddx <= 25.0 and ddz <= 25.0
            if not (near or (me > 0 and plc > 0 and abs(plc - me) == 1)):
                continue
            oname = _cstr(b, ob, 64)
            ocar = f"car {_i(b, ob + 72)}"
            if near:
                others_meta.append({"pos": opos, "name": oname, "position": max(0, plc), "car": ocar})
            odist = _f(b, ob + 140)
            if me > 1 and plc == me - 1:
                dm = (odist - my_d) % tlen if odist > 0 else math.hypot(opos[0] - fr.pos[0], opos[2] - fr.pos[2])
                fr.car_ahead = {"name": oname, "position": plc, "car": ocar,
                                "distance_m": round(max(1.0, dm)), "gap_s": fr.gap_ahead}
            elif me >= 1 and plc == me + 1:
                dm = (my_d - odist) % tlen if odist > 0 else math.hypot(opos[0] - fr.pos[0], opos[2] - fr.pos[2])
                fr.car_behind = {"name": oname, "position": plc, "car": ocar,
                                 "distance_m": round(max(1.0, dm)), "gap_s": fr.gap_behind}
        fr.others = others_pos
        if others_meta:
            fr.others_meta = others_meta
        return fr



IRSDK_MMF = "Local\\IRSDKMemMapFileName"
_IR_HDR = struct.Struct("<10i")            # ver, status, tickRate, sessionInfoUpdate, sessionInfoLen, sessionInfoOffset,
                                            # numVars, varHeaderOffset, numBuf, bufLen
_IR_VARBUF = struct.Struct("<2i")          # tickCount, bufOffset (then 2 pad ints); 4 of them from offset 48
_IR_VARHDR = struct.Struct("<3i?3x32s")    # type, offset, count, countAsTime, name (desc/unit follow; 144 bytes each)
_IR_FMT = {0: "c", 1: "?", 2: "i", 3: "I", 4: "f", 5: "d"}
_IR_SIZE = {0: 1, 1: 1, 2: 4, 3: 4, 4: 4, 5: 8}
# irsdk_Flags
_IR_FLAG_YELLOW, _IR_FLAG_BLUE, _IR_FLAG_YELLOW_WAVING = 0x8, 0x20, 0x100
_IR_FLAG_CAUTION, _IR_FLAG_CAUTION_WAVING = 0x4000, 0x8000


def _ir_session_info(text):
    """The few fields SimCoach needs from iRacing's session YAML, without a YAML library."""
    def field(name, src=text):
        m = re.search(rf"^\s*{name}:\s*(.*?)\s*$", src, re.MULTILINE)
        return m.group(1).strip().strip('"') if m else None

    def num(v):
        m = re.match(r"-?\d+(?:\.\d+)?", v or "")
        return float(m.group(0)) if m else None
    info = {"track": field("TrackDisplayName") or field("TrackName") or "iRacing track"}
    km = num(field("TrackLength"))
    info["track_len"] = km * 1000.0 if km else None
    info["redline"] = num(field("DriverCarRedLine")) or 0.0
    info["fuel_cap"] = num(field("DriverCarFuelMaxLtr")) or 0.0
    me = num(field("DriverCarIdx"))
    info["car_idx"] = int(me) if me is not None else None
    info["car"], cars, drivers = "iRacing car", 0, {}
    for blk in re.split(r"^\s*-\s+CarIdx:\s*", text, flags=re.MULTILINE)[1:]:
        idx = num(blk.split("\n", 1)[0])
        body = blk.split("\n- ", 1)[0]
        if idx is None:
            continue
        name = field("UserName", body) or ""
        drivers[int(idx)] = {"name": name, "car": field("CarScreenName", body) or ""}
        if field("CarIsPaceCar", body) == "1" or field("IsSpectator", body) == "1":
            continue
        cars += 1
        if info["car_idx"] is not None and int(idx) == info["car_idx"]:
            info["car"] = field("CarScreenName", body) or info["car"]
    info["cars"], info["drivers"] = cars, drivers
    sessions = {}
    for blk in re.split(r"^\s*-\s+SessionNum:\s*", text, flags=re.MULTILINE)[1:]:
        n = num(blk.split("\n", 1)[0])
        if n is None:
            continue
        typ = (field("SessionType", blk) or "").lower()
        laps = num(field("SessionLaps", blk))
        sessions[int(n)] = {"type": "race" if "race" in typ else ("qualifying" if "qual" in typ else "practice"),
                            "laps": int(laps) if laps else 0}
    info["sessions"] = sessions
    return info


class IRacingReader(Reader):
    """iRacing through its SDK shared memory: a header, variable descriptions, rotating data buffers (the newest
    one is read) and a YAML text block with track, car and session details."""
    name = "iRacing"
    CAP_BLOCKS = (("irsdk", "m", None),)
    WANT = ("Speed", "Throttle", "Brake", "SteeringWheelAngle", "SteeringWheelAngleMax", "Gear", "RPM",
            "LapDistPct", "LapCompleted", "LapCurrentLapTime", "LapLastLapTime", "OnPitRoad", "PlayerTrackSurface",
            "FuelLevel", "PlayerCarPosition", "PlayerCarIdx", "SessionNum", "SessionState", "SessionFlags",
            "SessionTimeRemain", "WaterTemp", "OilTemp", "CarIdxPosition", "CarIdxF2Time", "IsOnTrack")

    def __init__(self):
        self.m = None
        self._vars, self._layout_key = {}, None
        self._info, self._info_upd = None, None

    def close(self):
        if self.m:
            self.m.close()
            self.m = None
        self._vars, self._layout_key, self._info, self._info_upd = {}, None, None, None

    def connected(self):
        if not running("iracingsim"):
            self.close()
            return False
        if self.m is None:
            self.m = SharedMem.open(IRSDK_MMF)
        if self.m is None:
            return False
        return bool(_IR_HDR.unpack_from(self.m[0:40], 0)[1] & 1)

    def _load_vars(self, hdr):
        n_vars, vh_off = hdr[6], hdr[7]
        if (n_vars, vh_off) == self._layout_key:
            return
        raw = self.m[vh_off:vh_off + n_vars * 144]
        out = {}
        for k in range(n_vars):
            typ, off, cnt, _ast, name = _IR_VARHDR.unpack_from(raw, k * 144)
            name = name.split(b"\0", 1)[0].decode("latin-1")
            if name in self.WANT and typ in _IR_FMT:
                out[name] = (typ, off, max(1, cnt))
        self._vars, self._layout_key = out, (n_vars, vh_off)

    def _get(self, buf, name, default=None):
        v = self._vars.get(name)
        if v is None:
            return default
        typ, off, cnt = v
        if cnt == 1:
            return struct.unpack_from("<" + _IR_FMT[typ], buf, off)[0]
        return struct.unpack_from(f"<{cnt}{_IR_FMT[typ]}", buf, off)

    def read(self):
        hdr = _IR_HDR.unpack_from(self.m[0:40], 0)
        if not hdr[1] & 1 or hdr[8] < 1 or hdr[9] <= 0:
            return None
        self._load_vars(hdr)
        if hdr[3] != self._info_upd or self._info is None:
            raw = self.m[hdr[5]:hdr[5] + hdr[4]].split(b"\0", 1)[0]
            self._info, self._info_upd = _ir_session_info(raw.decode("latin-1", "replace")), hdr[3]
        bufs = [_IR_VARBUF.unpack_from(self.m[48 + 16 * k:48 + 16 * k + 8], 0) for k in range(min(4, hdr[8]))]
        tick, off = max(bufs)
        slot = 48 + 16 * bufs.index((tick, off))
        buf = self.m[off:off + hdr[9]]
        if _IR_VARBUF.unpack_from(self.m[slot:slot + 8], 0)[0] != tick:
            return None                                   # iRacing rewrote that buffer while we copied it: next frame
        g = lambda n, d=None: self._get(buf, n, d)
        info = self._info
        ses = info["sessions"].get(g("SessionNum", 0) or 0, {"type": "practice", "laps": 0})
        smax = g("SteeringWheelAngleMax", 0.0) or 0.0
        surf = g("PlayerTrackSurface", 3)
        laps_done = max(0, g("LapCompleted", 0) or 0)
        fr = Frame("iRacing", info["track"], info["car"], laps_done, max(0.0, min(0.99999, g("LapDistPct", 0.0) or 0.0)),
                   (g("Speed", 0.0) or 0.0) * 3.6, g("Throttle", 0.0) or 0.0, g("Brake", 0.0) or 0.0,
                   (-(g("SteeringWheelAngle", 0.0) or 0.0) / smax) if smax > 0.1 else 0.0,
                   g("Gear", 0) or 0, g("RPM", 0.0) or 0.0, max(0.0, g("LapCurrentLapTime", 0.0) or 0.0),
                   max(0.0, g("LapLastLapTime", 0.0) or 0.0), bool(g("OnPitRoad", False)) or surf in (1, 2), surf == 0,
                   fuel=max(0.0, g("FuelLevel", 0.0) or 0.0), track_len=info["track_len"], max_rpm=info["redline"],
                   session=ses["type"], position=max(0, g("PlayerCarPosition", 0) or 0), cars=info["cars"],
                   race_laps=ses["laps"] if ses["type"] == "race" else 0, fuel_cap=info["fuel_cap"])
        tleft = g("SessionTimeRemain")
        fr.time_left = tleft if (tleft is not None and 0 < tleft < 86400 and not fr.race_laps) else None
        fr.race_over = bool(ses["type"] == "race" and (g("SessionState", 0) or 0) >= 5)
        water, oil = g("WaterTemp"), g("OilTemp")
        fr.water_temp = water if water and 1.0 < water < 250.0 else None
        fr.oil_temp = oil if oil and 1.0 < oil < 250.0 else None
        fl = g("SessionFlags", 0) or 0
        fr.flag = ("fcy" if fl & (_IR_FLAG_CAUTION | _IR_FLAG_CAUTION_WAVING) else
                   "yellow" if fl & (_IR_FLAG_YELLOW | _IR_FLAG_YELLOW_WAVING) else
                   "blue" if fl & _IR_FLAG_BLUE else None)
        me, pos, f2 = g("PlayerCarIdx"), g("CarIdxPosition"), g("CarIdxF2Time")
        if me is not None and pos and f2 and 0 <= me < len(pos) and fr.position > 0 and ses["type"] == "race":
            by_pos = {p: i for i, p in enumerate(pos) if p > 0}
            mine = f2[me]
            a, b = by_pos.get(fr.position - 1), by_pos.get(fr.position + 1)
            ga = mine - f2[a] if a is not None else None
            gb = f2[b] - mine if b is not None else None
            fr.gap_ahead = ga if ga is not None and 0 < ga < 600 else None
            fr.gap_behind = gb if gb is not None and 0 < gb < 600 else None
            names = info["drivers"]
            if a is not None and fr.gap_ahead:
                fr.car_ahead = {"name": names.get(a, {}).get("name", ""), "position": fr.position - 1,
                                "car": names.get(a, {}).get("car", ""), "gap_s": fr.gap_ahead}
            if b is not None and fr.gap_behind:
                fr.car_behind = {"name": names.get(b, {}).get("name", ""), "position": fr.position + 1,
                                 "car": names.get(b, {}).get("car", ""), "gap_s": fr.gap_behind}
        return fr


def _udp_owner(port):
    """(local ip, process name) of another program's UDP socket on `port`, or None."""
    try:
        import psutil
        me = os.getpid()
        for c in psutil.net_connections(kind="udp4"):
            if c.laddr and c.laddr.port == port and c.pid and c.pid != me:
                try:
                    name = psutil.Process(c.pid).name()
                except Exception:
                    name = "?"
                return c.laddr.ip, name
    except Exception:
        pass
    return None


def _no_connreset(sock):
    """Windows: a UDP send to a closed port makes the next recv fail (WSAECONNRESET). Turn that off."""
    try:
        import socket
        sock.ioctl(socket.SIO_UDP_CONNRESET, False)
    except Exception:
        pass


class _UDPPort:
    """One socket per UDP port, shared by every reader that wants it (F1 25 and DiRT Rally 2.0 can both use 20777).
    - Port free: bind 127.0.0.1:<port> normally ("direct").
    - SimHub running and listening on 0.0.0.0:<port>: bind 127.0.0.1:<port> with SO_REUSEADDR and pass every packet
      on to 127.0.0.2:<port>, which SimHub's 0.0.0.0 socket receives and ours doesn't, so both get the stream and
      nothing loops ("relay"). Only done when SimHub's socket is a wildcard one; anything else is left alone.
    - SimHub starts while we hold the port: release it so SimHub can bind, then join as a relay.
    - Never raises: if the port can't be used, the reader keeps working from its fallback port."""
    _ports, _lock = {}, threading.Lock()
    log = staticmethod(file_log)
    share = True

    @classmethod
    def subscribe(cls, port, reader, primary):
        with cls._lock:
            hub = cls._ports.get(port)
            if hub is None:
                hub = cls._ports[port] = cls(port)
            if primary and getattr(reader, "share_port", True):
                hub.primary = True
                hub.procs = tuple(set(hub.procs) | set(getattr(reader, "procs", ())))
            hub.readers.add(reader)
            hub.start()
        return hub

    @classmethod
    def unsubscribe(cls, port, reader):
        with cls._lock:
            hub = cls._ports.get(port)
            if hub is not None:
                hub.readers.discard(reader)
                if not hub.readers:
                    hub.close()
                    del cls._ports[port]

    def __init__(self, port):
        self.port, self.primary, self.readers = port, False, set()
        self.procs = ()
        self.sock = self.out = None
        self.mode = None
        self.wait_until = 0.0
        self.simhub_was = None
        self.game_since = None
        self._closed = False
        self._said = None
        self._started = False

    def start(self):
        if not self._started:
            self._started = True
            threading.Thread(target=self._run, daemon=True, name=f"udp-{self.port}").start()

    def _note(self, msg):
        if msg != self._said:
            self._said = msg
            self.log(f"UDP {self.port}: {msg}")

    def _bind(self, reuse):
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if reuse:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", self.port))
        except OSError:
            s.close()
            return None
        s.settimeout(0.5)
        _no_connreset(s)
        return s

    def _drop(self):
        for x in (self.sock, self.out):
            try:
                if x is not None:
                    x.close()
            except Exception:
                pass
        self.sock = self.out = None
        self.mode = None

    def _manage(self, now):
        """Private ports (EA WRC's 20790, fallbacks): just bind. Ports SimHub may use (20777):
        - SimHub not running: bind directly. If SimHub starts later, hand the port over once.
        - SimHub running: relay if it holds the port on 0.0.0.0. Otherwise wait until the game is running and give
          SimHub ~10 s to take the port first; only then bind directly, and let go when the game closes.
          No grabbing and releasing in a loop."""
        if not self.primary:
            if self.sock is None:
                self._bind_direct()
            return
        simhub = _UDPPort.share and running("simhubwpf", "simhub.exe")
        fresh = simhub and self.simhub_was is False
        self.simhub_was = simhub
        game = running(*self.procs) if self.procs else True
        if self.game_since is None and game:
            self.game_since = now
        elif not game:
            self.game_since = None
        if not simhub:
            if self.mode == "relay":
                self._drop()
            if self.sock is None:
                self._bind_direct()
            return
        if self.mode == "direct":
            if fresh:
                self._drop()
                self.wait_until = now + 15.0
                self._note("SimHub started, handing it the port.")
            elif not game:
                self._drop()
            return
        owner = _udp_owner(self.port)
        if self.mode == "relay":
            if owner is None:
                self._drop()
            return
        if owner and owner[0] in ("0.0.0.0", "::"):
            s = self._bind(reuse=True)
            if s is not None:
                import socket
                self.sock, self.mode = s, "relay"
                self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                _no_connreset(self.out)
                self._note(f"sharing with {owner[1]} (relaying to it on 127.0.0.2).")
            return
        if owner is not None:
            self._note(f"in use by {owner[1]} ({owner[0]}); using the fallback port instead.")
            return
        if game and now - self.game_since >= 10 and now >= self.wait_until:
            self._bind_direct()

    def _bind_direct(self):
        s = self._bind(reuse=False)
        if s is not None:
            self.sock, self.mode = s, "direct"
            self._note("listening.")
        else:
            owner = _udp_owner(self.port)
            who = owner[1] if owner else "another program"
            self._note(f"in use by {who}" + ("; using the fallback port instead." if self.primary else "."))

    def _run(self):
        next_check = 0.0
        while not self._closed:
            now = time.monotonic()
            if now >= next_check:
                next_check = now + 2.0
                try:
                    self._manage(now)
                except Exception as e:
                    self._note(f"error {e}")
            s = self.sock
            if s is None:
                time.sleep(0.25)
                continue
            try:
                data, _ = s.recvfrom(4096)
            except Exception:
                continue
            if self.mode == "relay" and self.out is not None:
                try:
                    self.out.sendto(data, ("127.0.0.2", self.port))
                except OSError:
                    pass
            for r in list(self.readers):
                r._feed(data)

    def close(self):
        self._closed = True
        self._drop()


class _UDPReader(Reader):
    port = 0
    fallback = None

    def __init__(self, port=None, fallback=None):
        if port:
            self.port = int(port)
        if fallback:
            self.fallback = int(fallback)
        self._closed = False
        self.last_rx = 0.0
        self.frame: Optional[Frame] = None
        self.lock = threading.Lock()
        self._plock = threading.Lock()
        self._ports = [self.port] + ([self.fallback] if self.fallback and self.fallback != self.port else [])
        self._cap_buf = None
        for i, pt in enumerate(self._ports):
            _UDPPort.subscribe(pt, self, primary=(i == 0))

    def cap_start(self):
        with self._plock:
            self._cap_buf = []

    def cap_take(self):
        """Packets received since the last call (a capture drains them a few times a second)."""
        with self._plock:
            got, self._cap_buf = self._cap_buf, ([] if self._cap_buf is not None else None)
        return got or []

    def cap_stop(self):
        with self._plock:
            self._cap_buf = None

    def _feed(self, data):
        if self._closed:
            return
        with self._plock:
            cb = self._cap_buf
            if cb is not None and len(cb) < 50000:
                cb.append((time.monotonic(), bytes(data)))
            try:
                f = self.parse(data)
            except Exception:
                f = None
            if f is not None:
                with self.lock:
                    pend = self.frame
                    if pend is not None and pend.restart and not f.restart:
                        f.restart = True
                    self.frame, self.last_rx = f, time.monotonic()

    def close(self):
        self._closed = True
        for pt in self._ports:
            _UDPPort.unsubscribe(pt, self)

    def parse(self, data):
        raise NotImplementedError

    def connected(self):
        return not self._closed and (time.monotonic() - self.last_rx < 2.0)

    def read(self):
        with self.lock:
            f, self.frame = self.frame, None
        return f


class _StageTracker:
    """Rally stages: one run = one 'lap'. Restarts without finishing are flagged, not scored."""

    def __init__(self):
        self.runs = 0
        self.prev_t = None
        self.prev_pct = 0.0
        self.last_time = 0.0
        self.key = None
        self.done = False

    def step(self, t, pct, key=None, finished=False):
        """finished: the raw stage distance reached the stage length. The run counts right there, so a
        stage that's driven once and left (next stage, results, quit) is still recorded."""
        if key != self.key:
            self.key = key
            self.runs, self.prev_t, self.prev_pct, self.last_time = 0, None, 0.0, 0.0
            self.done = False
        restart = False
        if self.prev_t is not None and t < self.prev_t - 1.0:
            if self.done:
                self.done = False
                restart = True
            elif self.prev_pct > 0.98:
                self.runs += 1
                self.last_time = self.prev_t
            else:
                restart = True
        elif finished and not self.done and t > 1.0 and self.prev_t is not None:
            self.done = True
            self.runs += 1
            self.last_time = t
        self.prev_t, self.prev_pct = t, pct
        return self.runs, self.last_time, restart


WRC_PORT = 20790
WRC_CHANNELS = [
    ("packet_uid", "Q"), ("stage_current_time", "f"), ("stage_current_distance", "d"), ("stage_length", "d"),
    ("vehicle_speed", "f"), ("vehicle_throttle", "f"), ("vehicle_brake", "f"), ("vehicle_steering", "f"),
    ("vehicle_gear_index", "B"), ("vehicle_gear_index_neutral", "B"), ("vehicle_gear_index_reverse", "B"),
    ("vehicle_engine_rpm_current", "f"), ("vehicle_engine_rpm_max", "f"),
    ("vehicle_cp_forward_speed_fl", "f"), ("vehicle_cp_forward_speed_fr", "f"),
    ("vehicle_cp_forward_speed_bl", "f"), ("vehicle_cp_forward_speed_br", "f"),
    ("vehicle_id", "H"), ("location_id", "H"), ("route_id", "H"),
]
WRC_FMT = "<" + "".join(t for _, t in WRC_CHANNELS)
_S_WRC = struct.Struct(WRC_FMT)
_WRC_SIZE = _S_WRC.size
_U_WRC = _S_WRC.unpack_from


class EAWRCReader(_UDPReader):
    name = "EA WRC"
    port = WRC_PORT
    share_port = False

    def __init__(self, port=None):
        self.stage = _StageTracker()
        self.ids = {}
        try:
            p = os.path.join(_documents_dir(), "My Games", "WRC", "telemetry", "readme", "ids.json")
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
            for k in ("vehicles", "locations", "routes"):
                self.ids[k] = {x["id"]: x.get("name", "") for x in d.get(k, [])}
        except Exception:
            pass
        super().__init__(port)

    def parse(self, data):
        if len(data) < _WRC_SIZE:
            return None
        (_uid, cur_t, cur_d, L, spd, thr, brk, steer,
         g, g_neut, g_rev, rpm, rpm_max,
         w_fl, w_fr, w_bl, w_br, vid, lid, rid) = _U_WRC(data, 0)
        if L <= 100:
            return None
        pct = max(0.0, min(0.99999, cur_d / L))
        runs, last, restart = self.stage.step(cur_t, pct, (vid, lid, rid), finished=cur_d >= L)
        gear = -1 if g == g_rev else 0 if g == g_neut else g
        sp = spd * 3.6
        wk = [abs(w_fl) * 3.6, abs(w_fr) * 3.6, abs(w_bl) * 3.6, abs(w_br) * 3.6]
        loc = self.ids.get("locations", {}).get(lid, f"location {lid}")
        route = self.ids.get("routes", {}).get(rid, f"stage {rid}")
        car = self.ids.get("vehicles", {}).get(vid, f"car {vid}")
        return Frame("EA WRC", f"{loc} - {route}", car, runs, pct, sp, thr, brk,
                     steer, gear, rpm, cur_t, last,
                     False, False, 0.0, L, None, rpm_max, wk, None, restart)


F1_TRACKS = {0: "Melbourne", 2: "Shanghai", 3: "Sakhir", 4: "Catalunya", 5: "Monaco", 6: "Montreal", 7: "Silverstone",
             9: "Hungaroring", 10: "Spa", 11: "Monza", 12: "Singapore", 13: "Suzuka", 14: "Abu Dhabi", 15: "Austin",
             16: "Interlagos", 17: "Red Bull Ring", 19: "Mexico City", 20: "Baku", 26: "Zandvoort", 27: "Imola",
             29: "Jeddah", 30: "Miami", 31: "Las Vegas", 32: "Losail", 39: "Silverstone Reverse",
             40: "Red Bull Ring Reverse", 41: "Zandvoort Reverse"}


F1_TEAMS = {0: "Mercedes", 1: "Ferrari", 2: "Red Bull", 3: "Williams", 4: "Aston Martin",
            5: "Alpine", 6: "RB", 7: "Haas", 8: "McLaren", 9: "Sauber"}


class F1Reader(_UDPReader):
    """F1 25: in-game Settings > Telemetry: UDP On, port 20777, format 2025."""
    name = "F1 25"
    port = 20777
    procs = ("f1_25", "f1_24", "f1_23")

    def __init__(self, port=None, fallback=None):
        self.track, self.track_len = "F1 circuit", None
        self.lap = None
        self.tel = None
        self.session, self.race_laps, self.time_left, self.rain = None, 0, None, None
        self.rain_in_10 = self.rain_in_30 = None
        self.fia_flag = self.sc = None
        self._sess_ok = True
        self.position, self.gap_ahead, self.gap_behind = 0, None, None
        self.fuel, self.fuel_cap, self.wear = 0.0, 0.0, None
        self.pos, self.right, self.others, self.others_meta, self.cars = None, None, None, None, 0
        self.participants = {}
        self.car_positions = {}
        self.race_over = False
        self.car_ahead, self.car_behind = None, None
        self._uid = None
        super().__init__(port, fallback)

    @staticmethod
    def _forecast(d, st):
        """Session packet weather forecast (F1 23-25): m_numWeatherForecastSamples @155, then up to 64 samples of 8
        bytes from @156 (sessionType, timeOffset in minutes, weather, track temp, change, air temp, change, rain %).
        The worst weather forecast for this session within 10 minutes and from 10 to 30 minutes, 0 dry .. 1 storm."""
        n = d[155] if len(d) > 155 else 0
        if not 0 < n <= 64 or len(d) < 156 + n * 8:
            return None, None
        soon = later = 0.0
        found = False
        for k in range(n):
            o = 156 + k * 8
            if d[o] != st:
                continue
            found = True
            off, w = d[o + 1], {3: 0.3, 4: 0.7, 5: 1.0}.get(d[o + 2], 0.0)
            if 0 < off <= 10:
                soon = max(soon, w)
            elif 10 < off <= 30:
                later = max(later, w)
        return (soon, later) if found else (None, None)

    def _new_session(self):
        """A new session (or a restart): nothing from the last one may leak into the first frames of this one."""
        self.lap = None
        self.race_over = False
        self.position, self.gap_ahead, self.gap_behind, self.cars = 0, None, None, 0
        self.fuel, self.fuel_cap = 0.0, 0.0
        self.pos, self.right, self.wear, self.others, self.others_meta = None, None, None, None, None
        self.participants, self.car_positions = {}, {}
        self.car_ahead = self.car_behind = None
        self.fia_flag = self.sc = None
        self.session, self.race_laps, self.time_left, self.rain = None, 0, None, None
        self.rain_in_10 = self.rain_in_30 = None
        self._sess_ok = False

    def parse(self, d):
        if len(d) < 29:
            return None
        fmt, yr, _ma, _mi, _pv, pid = _U_F1_HDR(d, 0)
        if fmt not in (2023, 2024, 2025) or yr != fmt - 2000 or pid > 15:
            return None
        me = d[27]
        if me >= 22:
            return None
        uid = d[7:15]
        if uid != self._uid and uid != _ZERO8:
            if self._uid is not None:
                self._new_session()
            self._uid = uid
        if pid == 0 and len(d) >= 29 + 22 * 60:
            cars, meta = [], []
            o = 29 + me * 60
            mx, my, mz = self.pos = _U_3f(d, o)
            rx, _ry, rz = _U_3h(d, o + 30)
            self.right = (rx / 32767.0, rz / 32767.0)
            for k in range(22):
                if k == me:
                    continue
                o = 29 + k * 60
                x, y, z = _U_3f(d, o)
                if x or y or z:
                    ddx, ddz = abs(x - mx), abs(z - mz)
                    if ddx <= 10.0 and ddz <= 10.0:
                        cars.append((x, y, z))
                    if ddx <= 25.0 and ddz <= 25.0:
                        nm, tm = self.participants.get(k, (f"Car {k + 1}", "F1 car"))
                        cpos = self.car_positions.get(k, (0, 0.0))[0]
                        meta.append({"pos": (x, y, z), "name": nm, "position": cpos, "car": tm})
            self.others = cars
            self.others_meta = meta or None
            return None
        if pid == 1 and len(d) > 40:
            self._sess_ok = True
            self.track_len = _U_H(d, 33)[0] or None
            self.track = F1_TRACKS.get(_U_b(d, 36)[0], "F1 circuit")
            st = d[35]
            if fmt == 2023:
                self.session = "practice" if 1 <= st <= 4 else "qualifying" if 5 <= st <= 9 else \
                    "race" if 10 <= st <= 12 else None
            else:
                self.session = "practice" if 1 <= st <= 4 else "qualifying" if 5 <= st <= 14 else \
                    "race" if 15 <= st <= 17 else None
            self.race_laps = d[32] if self.session == "race" else 0
            tl = _U_H(d, 38)[0]
            self.time_left = float(tl) if tl and not self.race_laps else None
            self.rain = {3: 0.3, 4: 0.7, 5: 1.0}.get(d[29], 0.0)
            self.sc = {1: "sc", 2: "vsc"}.get(d[153]) if len(d) > 153 else None
            self.rain_in_10, self.rain_in_30 = self._forecast(d, st)
            return None
        if pid == 7:
            per = (len(d) - 29) // 22
            o = 29 + me * per
            if per >= 17 and o + 17 <= len(d):
                self.fuel, self.fuel_cap = _U_2f(d, o + 5)
            if per >= 29 and o + 29 <= len(d):
                self.fia_flag = {2: "blue", 3: "yellow"}.get(_U_b(d, o + 28)[0])
            return None
        if pid == 10:
            per = (len(d) - 29) // 22
            o = 29 + me * per
            if per >= 16 and o + 16 <= len(d):
                w = _U_4f(d, o)
                if all(0.0 <= x <= 100.0 for x in w):
                    self.wear = [w[2], w[3], w[0], w[1]]
            return None
        if pid == 4 and len(d) > 30:
            per = (len(d) - 30) // 22
            if per >= 55:
                for k in range(22):
                    b0 = 30 + k * per
                    if b0 + 55 <= len(d):
                        t_id = d[b0 + 3]
                        nm = _cstr(d, b0 + 7, 48)
                        t_name = F1_TEAMS.get(t_id, "F1 car")
                        if nm:
                            self.participants[k] = (nm, t_name)
            return None
        if pid == 2:
            per = (len(d) - 31) // 22
            if per < 36:
                return None
            o = 29 + me * per
            if fmt == 2023:
                if o + 36 > len(d):
                    return None
                self.lap = _U_II(d, o) + (_f(d, o + 18), d[o + 31], d[o + 32], d[o + 35])
                p_off, ld_off, rs_off = 30, 18, 43

                def gap(base):
                    return _U_H(d, base + 14)[0] / 1000.0
            else:
                if o + 38 > len(d):
                    return None
                self.lap = _U_II(d, o) + (_f(d, o + 20), d[o + 33], d[o + 34], d[o + 37])
                p_off, ld_off, rs_off = 32, 20, 45

                def gap(base):
                    return _U_H(d, base + 14)[0] / 1000.0 + d[base + 16] * 60.0
            self.position = d[o + p_off]
            res_status = d[o + rs_off] if (per > rs_off and o + rs_off < len(d)) else 0
            lapnum_me = self.lap[3]
            self.race_over = bool(self.session == "race" and (
                res_status == 3 or (self.race_laps > 0 and lapnum_me > self.race_laps)
            ))
            ga = gap(o) if self.position > 1 else 0.0
            self.gap_ahead = ga if ga > 0 else None
            self.gap_behind, self.cars = None, 0
            self.car_ahead = self.car_behind = None
            my_ld = self.lap[2]
            tlen = self.track_len or 5000.0
            for k in range(22):
                b0 = 29 + k * per
                if b0 + p_off < len(d) and d[b0 + p_off]:
                    cpos = d[b0 + p_off]
                    cld = _f(d, b0 + ld_off)
                    self.car_positions[k] = (cpos, cld)
                    self.cars += 1
                    if self.position > 1 and cpos == self.position - 1:
                        nm, tm = self.participants.get(k, (f"Car {k + 1}", "F1 car"))
                        dm = (cld - my_ld) % tlen
                        self.car_ahead = {"name": nm, "position": cpos, "car": tm,
                                          "distance_m": round(max(1.0, dm)), "gap_s": self.gap_ahead}
                    elif self.position >= 1 and cpos == self.position + 1:
                        g = gap(b0)
                        self.gap_behind = g if g > 0 else None
                        nm, tm = self.participants.get(k, (f"Car {k + 1}", "F1 car"))
                        dm = (my_ld - cld) % tlen
                        self.car_behind = {"name": nm, "position": cpos, "car": tm,
                                           "distance_m": round(max(1.0, dm)), "gap_s": self.gap_behind}
            return None
        if pid != 6 or self.lap is None or not self._sess_ok or len(d) < 29 + (me + 1) * 60:
            return None
        o = 29 + me * 60
        speed, thr, steer, brk = _U_Hfff(d, o)
        gear = _U_b(d, o + 15)[0]
        rpm = _U_H(d, o + 16)[0]
        t_rl, t_rr, t_fl, t_fr = d[o + 34:o + 38]
        p_rl, p_rr, p_fl, p_fr = _U_4f(d, o + 40)
        eng_t = _U_H(d, o + 38)[0]
        last_ms, cur_ms, lapdist, lapnum, pit, invalid = self.lap
        L = self.track_len or 5000.0
        laps_done = self.race_laps if (self.race_over and self.race_laps > 0) else max(0, lapnum - 1)
        my_team = self.participants.get(me, ("", "F1 car"))[1]
        fr = Frame("F1 25", self.track, my_team, laps_done, max(0.0, lapdist) / L % 1.0, float(speed),
                   thr, brk, steer, gear, float(rpm), cur_ms / 1000.0, last_ms / 1000.0, pit != 0, False,
                   self.fuel, self.track_len, [t_fl, t_fr, t_rl, t_rr], 0.0, None, [p_fl, p_fr, p_rl, p_rr],
                   lap_invalid=invalid != 0)
        fr.session, fr.race_laps, fr.time_left, fr.rain = self.session, self.race_laps, self.time_left, self.rain
        fr.rain_in_10, fr.rain_in_30 = self.rain_in_10, self.rain_in_30
        fr.water_temp = float(eng_t) if 1 < eng_t < 250 else None
        fr.position, fr.cars, fr.gap_ahead, fr.gap_behind = self.position, self.cars, self.gap_ahead, self.gap_behind
        fr.fuel_cap, fr.tyre_wear = self.fuel_cap, self.wear
        fr.pos, fr.right, fr.others, fr.others_meta = self.pos, self.right, self.others, self.others_meta
        fr.race_over = self.race_over
        fr.car_ahead, fr.car_behind = self.car_ahead, self.car_behind
        fr.flag = self.sc or self.fia_flag
        return fr


class DR2Reader(_UDPReader):
    """DiRT Rally 2.0 'extradata=3' motion packet (SimCoach sets this up in hardware_settings_config.xml)."""
    name = "DiRT Rally 2.0"
    port = 20777
    fallback = 20779
    procs = ("dirtrally2",)

    def __init__(self, port=None, fallback=None):
        self.stage = _StageTracker()
        super().__init__(port, fallback)

    def parse(self, d):
        if len(d) != 264:
            return None
        v = _U_DR2(d, 0)
        L = v[61]
        g = v[33]
        if not (500 < L < 60000 and -200 < v[2] < L + 200 and 0 <= v[1] < 36000 and v[0] >= v[1] - 1
                and 0 <= g <= 10 and g == int(g) and 0 <= v[37] <= 2500 and 0 < v[63] <= 2500):
            return None
        pct = max(0.0, min(0.99999, v[2] / L))
        runs, last, restart = self.stage.step(v[1], pct, int(L), finished=v[2] >= L)
        wk = [abs(v[27]) * 3.6, abs(v[28]) * 3.6, abs(v[25]) * 3.6, abs(v[26]) * 3.6]
        gear = int(v[33]) if v[33] < 9 else -1
        return Frame("DiRT Rally 2.0", f"stage {int(L)} m", "rally car", runs, pct, v[7] * 3.6, v[29], v[31], v[30],
                     gear, v[37] * 10, v[1], last, bool(v[47]), False, v[45], L, None, v[63] * 10, wk, None, restart)


def available_readers(cfg=None, log=print):
    cfg = cfg or DEFAULT_CONFIG
    out = []
    if sys.platform != "win32":
        return out
    _UDPPort.share = bool(cfg.get("udp_share_simhub", True))
    _UDPPort.log = staticmethod(log)
    f1 = int(cfg.get("f1_port", 20777))
    dr2_fb = int(cfg.get("dr2_port", 20779))
    makers = [ACReader, ACEvoReader, LMUReader, RF2Reader, AMS2Reader, R3EReader, IRacingReader,
              lambda: EAWRCReader(), lambda: F1Reader(f1, 20778 if f1 != 20778 else None),
              lambda: DR2Reader(20777, dr2_fb if dr2_fb != 20777 else None)]
    for mk in makers:
        try:
            out.append(mk())
        except Exception as e:
            log(f"Reader unavailable: {e}")
    return out



_GOOGLE_TLDS = {
    "en-GB": ("co.uk", "en-GB"),
    "en-US": ("com", "en-US"),
    "en-AU": ("com.au", "en-AU"),
    "en-IE": ("ie", "en-IE"),
    "en-CA": ("ca", "en-CA"),
    "en-IN": ("co.in", "en-IN"),
    "en-ZA": ("co.za", "en-ZA"),
    "co.uk": ("co.uk", "en-GB"),
    "com": ("com", "en-US"),
    "com.au": ("com.au", "en-AU"),
    "ie": ("ie", "en-IE"),
    "ca": ("ca", "en-CA"),
    "co.in": ("co.in", "en-IN"),
    "co.za": ("co.za", "en-ZA"),
}
_KOKORO_VOICE_RE = re.compile(r"^(?:af|am|bf|bm)_[a-z0-9]+$")
_KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx"
_KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"


class Voice:
    """One output thread for speech plus instant tones.
    Supports Microsoft neural voices (edge-tts), Google voices (gTTS / Google Translate TTS),
    and Kokoro local neural voices (kokoro-onnx / kokoro), with Windows SAPI fallback.
    Message kinds: 'cue' (dropped if it can't play within 1 s), 'info', 'answer' (long ones wait for a
    straight), 'urgent'. Phrases are synthesised ahead of time where possible so cues play instantly."""

    CACHE_MAX = 120

    def __init__(self, cfg, enabled=True, log=print):
        self.cfg, self.log, self.enabled = cfg, log, enabled
        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.synth_q: "queue.Queue[tuple]" = queue.Queue()
        self.busy_until = 0.0
        self._last_spoke_end = -999.0
        self.last_text = ""
        self.hold = threading.Event()
        self.on_straight = threading.Event()
        self.on_straight.set()
        self._sapi = None
        self._mixer = False
        self._mlock = threading.RLock()
        self._cache_lock = threading.Lock()
        self._kokoro_lock = threading.Lock()
        self._kokoro = None
        self._kokoro_pipe = {}
        self._kokoro_dl = False
        self._kokoro_retry = 0.0
        self._tones = {}
        self._cache = OrderedDict()
        self._queued_synth = set()
        self._inflight: dict[str, threading.Event] = {}
        self._tmp = tempfile.mkdtemp(prefix="simcoach_")
        atexit.register(shutil.rmtree, self._tmp, True)
        self.events = None
        self._item = None
        self.spot_q: "queue.Queue[tuple]" = queue.Queue()
        self._tls = threading.local()
        self.preempt = threading.Event()
        self._cancel = set()
        self._deferred, self._resumes = [], []
        threading.Thread(target=self._run, daemon=True, name="voice").start()
        threading.Thread(target=self._synth_worker, daemon=True, name="voice-synth").start()

    @staticmethod
    @lru_cache(maxsize=64)
    def _resolve_voice(vname: Optional[str]) -> tuple[str, str, str]:
        """Return (engine, voice_id, engine_label) for a configured voice identifier."""
        v = (vname or "en-GB-RyanNeural").strip()
        vl = v.lower()
        if vl == "google" or vl.startswith(("google:", "gtts:")):
            sub = v.split(":", 1)[1].strip() if ":" in v else "en-GB"
            return "google", (sub or "en-GB"), "Google voice"
        if vl == "kokoro" or vl.startswith("kokoro:") or _KOKORO_VOICE_RE.match(vl):
            sub = v.split(":", 1)[1].strip() if ":" in v else ("bm_george" if vl == "kokoro" else vl)
            return "kokoro", (sub or "bm_george"), "Kokoro neural voice"
        return "edge", (v or "en-GB-RyanNeural"), "Microsoft neural voice"

    @staticmethod
    def duration(text):
        return 0.4 + len(text.split()) / 2.8

    def _key(self, text, voice=None):
        eng, vid, _ = self._resolve_voice(voice or self.cfg.get("voice"))
        return f"{eng}:{vid}|{self.cfg.get('speech_rate', 8)}|{text}"

    def latency(self, text, voice=None):
        if not self._mixer:
            return 0.15
        key = self._key(text, voice)
        with self._cache_lock:
            if key in self._cache:
                return 0.15
        eng, _, _ = self._resolve_voice(voice or self.cfg.get("voice"))
        if eng == "kokoro" and (self._kokoro is not None or self._kokoro_pipe):
            return 0.25
        return 0.9

    def idle(self, now):
        return (now >= self.busy_until and not self._deferred and not self._resumes
                and not self.hold.is_set() and self.q.empty() and self.spot_q.empty())

    def say(self, text, now, kind="info", voice=None, who="COACH"):
        """kind: 'cue', 'info', 'chat' (crew banter: cut short by any urgent call), 'answer', 'urgent', or 'spot'
        (spotter: jumps the queue and cuts in)."""
        self.log(f"{who}: {text}")
        self._cancel.discard(text)
        if kind == "spot":
            self.spot_q.put((text, kind, time.monotonic(), voice))
            self.preempt.set()
            return
        self.busy_until = max(now, self.busy_until) + self.duration(text) + self.latency(text, voice) + GAP_AFTER_TALK
        if kind != "cue":
            self.last_text = text
        self.q.put((text, kind, time.monotonic(), voice))

    def prefetch(self, text, voice=None):
        if not self.enabled or not text:
            return
        key = self._key(text, voice)
        with self._cache_lock:
            if key in self._cache or key in self._queued_synth:
                return
            self._queued_synth.add(key)
        self.synth_q.put((text, voice))

    def reconfigure(self):
        """Re-open the audio device / apply volume after settings change."""
        self.q.put(("", "__reinit__", time.monotonic(), None))

    def tone(self, freq, ms):
        """Short sine tone on the coach's audio device, mixed over speech. Used for braking countdowns."""
        BEEP_LOG.append((time.monotonic(), freq))
        if not self.enabled:
            return
        if not self._mixer:
            beep(freq, ms)
            return
        try:
            import numpy as np
            import pygame
            with self._mlock:
                snd = self._tones.get((freq, ms))
                if snd is None:
                    fr, _size, ch = pygame.mixer.get_init()
                    t = np.arange(int(fr * ms / 1000)) / fr
                    env = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.006)
                    w = (np.sin(2 * np.pi * freq * t) * env * 0.7 * 32767).astype(np.int16)
                    arr = np.ascontiguousarray(np.repeat(w[:, None], ch, axis=1) if ch > 1 else w)
                    snd = self._tones[(freq, ms)] = pygame.sndarray.make_sound(arr)
                snd.set_volume(float(self.cfg.get("volume", 0.9)))
                snd.play()
        except Exception as e:
            self.log(f"Tone failed: {e}")
            beep(freq, ms)

    def list_outputs(self):
        """Names of playback devices the coach can use."""
        try:
            import pygame
            import pygame._sdl2.audio as sdl2_audio
            with self._mlock:
                temp = not pygame.mixer.get_init()
                if temp:
                    pygame.mixer.init()
                names = list(sdl2_audio.get_audio_device_names(False))
                if temp:
                    pygame.mixer.quit()
            return names
        except Exception as e:
            self.log(f"Couldn't list audio devices: {e}")
            return []

    def _init_audio(self):
        if not self.enabled:
            return
        dev = self.cfg.get("audio_out") or None
        try:
            import pygame
            with self._mlock:
                if pygame.mixer.get_init():
                    pygame.mixer.quit()
                self._tones = {}
                try:
                    pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=512, devicename=dev)
                except Exception as e:
                    if dev:
                        self.log(f"Audio device '{dev}' unavailable ({e}); using the Windows default.")
                    pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=512)
                pygame.mixer.music.set_volume(float(self.cfg.get("volume", 0.9)))
            self._mixer = True
        except Exception as e:
            self._mixer = False
            self.log(f"Audio mixer unavailable: {e}")
        if sys.platform == "win32" and self._sapi is None:
            try:
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize()
                self._sapi = win32com.client.Dispatch("SAPI.SpVoice")
            except Exception:
                self._sapi = None
        if self._sapi is not None:
            try:
                self._sapi.Volume = int(float(self.cfg.get("volume", 0.9)) * 100)
                if dev:
                    for tok in self._sapi.GetAudioOutputs():
                        if dev.lower() in tok.GetDescription().lower():
                            self._sapi.AudioOutput = tok
                            break
            except Exception:
                pass

    def _synth_edge(self, text, vid, rate_val, part):
        import edge_tts
        rate = f"{int(rate_val):+d}%"
        loop = getattr(self._tls, "loop", None)
        if loop is None or loop.is_closed():
            loop = self._tls.loop = asyncio.new_event_loop()
        loop.run_until_complete(edge_tts.Communicate(text, vid, rate=rate).save(part))

    def _synth_google(self, text, vid, rate_val, part):
        tld, lang_tag = _GOOGLE_TLDS.get(vid, ("co.uk", "en-GB"))
        slow = int(rate_val) < -15
        try:
            from gtts import gTTS
            gTTS(text=text, lang="en", tld=tld, slow=slow).save(part)
            return
        except ImportError:
            pass
        import urllib.parse
        import urllib.request
        words = text.split()
        chunks, cur = [], []
        cur_len = 0
        for w in words:
            if cur and cur_len + len(w) + 1 > 180:
                chunks.append(" ".join(cur))
                cur, cur_len = [w], len(w)
            else:
                cur.append(w)
                cur_len += len(w) + (1 if cur_len else 0)
        if cur:
            chunks.append(" ".join(cur))
        spd = "0.24" if slow else "1"
        with open(part, "wb") as fh:
            for ch in (chunks or [text]):
                q = urllib.parse.quote(ch)
                url = (f"https://translate.googleapis.com/translate_tts?ie=UTF-8&client=tw-ob"
                       f"&tl={lang_tag}&ttsspeed={spd}&q={q}")
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    fh.write(resp.read())

    _KOKORO_MIN = {"kokoro-v1.0.int8.onnx": 50_000_000, "voices-v1.0.bin": 20_000_000}

    def _kokoro_paths(self):
        kdir = os.path.join(APP_DIR, "kokoro")
        return kdir, os.path.join(kdir, "kokoro-v1.0.int8.onnx"), os.path.join(kdir, "voices-v1.0.bin")

    def _kokoro_download(self):
        """Fetch the Kokoro model in the background (~115 MB, first use only). Speech carries on in the Microsoft
        voice meanwhile instead of the whole crew going silent while it downloads."""
        try:
            import urllib.request
            kdir, mpath, vpath = self._kokoro_paths()
            os.makedirs(kdir, exist_ok=True)
            self.log("Downloading the Kokoro voice model (first use only, ~115 MB)...")
            for url, dst in ((_KOKORO_MODEL_URL, mpath), (_KOKORO_VOICES_URL, vpath)):
                if os.path.exists(dst):
                    continue
                tmp = f"{dst}.part"
                req = urllib.request.Request(url, headers={"User-Agent": "SimCoach/1.0"})
                with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
                    shutil.copyfileobj(resp, out)
                if os.path.getsize(tmp) < self._KOKORO_MIN[os.path.basename(dst)]:
                    os.remove(tmp)
                    raise RuntimeError(f"download of {os.path.basename(dst)} was incomplete")
                os.replace(tmp, dst)
            self.log("Kokoro voice model ready.")
        except Exception as e:
            self._kokoro_retry = time.monotonic() + 300
            self.log(f"Kokoro download failed ({e}); using the Microsoft voice, will retry in 5 minutes.")
        finally:
            self._kokoro_dl = False

    def _ensure_kokoro_onnx(self):
        if self._kokoro is not None:
            return self._kokoro
        from kokoro_onnx import Kokoro
        if time.monotonic() < self._kokoro_retry:
            raise RuntimeError("Kokoro unavailable for now")
        _kdir, mpath, vpath = self._kokoro_paths()
        if not (os.path.exists(mpath) and os.path.exists(vpath)):
            with self._kokoro_lock:
                if not self._kokoro_dl:
                    self._kokoro_dl = True
                    threading.Thread(target=self._kokoro_download, daemon=True, name="kokoro-download").start()
            raise RuntimeError("Kokoro model still downloading")
        with self._kokoro_lock:
            if self._kokoro is None:
                try:
                    try:
                        import onnxruntime as _ort
                        _orig_is = _ort.InferenceSession
                        def _capped_is(*a, **kw):
                            if "sess_options" not in kw or kw["sess_options"] is None:
                                so = _ort.SessionOptions()
                                so.intra_op_num_threads = 2
                                so.inter_op_num_threads = 1
                                kw["sess_options"] = so
                            return _orig_is(*a, **kw)
                        _ort.InferenceSession = _capped_is
                        try:
                            self._kokoro = Kokoro(mpath, vpath)
                        finally:
                            _ort.InferenceSession = _orig_is
                    except ImportError:
                        self._kokoro = Kokoro(mpath, vpath)
                except Exception:
                    for pth in (mpath, vpath):
                        try:
                            os.remove(pth)
                        except Exception:
                            pass
                    self._kokoro_retry = time.monotonic() + 60
                    raise
            return self._kokoro

    def _synth_kokoro(self, text, vid, rate_val, part):
        import wave
        import numpy as np
        speed = max(0.5, min(2.0, 1.0 + int(rate_val) / 100.0))
        samples, sr = None, 24000
        try:
            kokoro = self._ensure_kokoro_onnx()
            lang = "en-gb" if vid.startswith("b") else "en-us"
            samples, sr = kokoro.create(text, voice=vid, speed=speed, lang=lang)
        except ImportError:
            from kokoro import KPipeline
            lang_code = "b" if vid.startswith("b") else "a"
            with self._kokoro_lock:
                pipe = self._kokoro_pipe.get(lang_code)
                if pipe is None:
                    pipe = self._kokoro_pipe[lang_code] = KPipeline(lang_code=lang_code)
            segs = [audio for _, _, audio in pipe(text, voice=vid, speed=speed) if audio is not None]
            if not segs:
                raise RuntimeError("Kokoro produced no audio")
            samples = np.concatenate([np.asarray(s, dtype=np.float32) for s in segs])
        pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        with wave.open(part, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(sr))
            wf.writeframes(pcm)

    def _synth(self, text, vname=None):
        """Return a path to a synthesised audio file of `text`, deduplicating concurrent requests."""
        eng, vid, _ = self._resolve_voice(vname or self.cfg.get("voice"))
        key = self._key(text, vname)
        wait_ev = None
        with self._cache_lock:
            path = self._cache.get(key)
            if path and os.path.exists(path):
                self._cache.move_to_end(key)
                self._queued_synth.discard(key)
                return path
            wait_ev = self._inflight.get(key)
            if wait_ev is None:
                my_ev = self._inflight[key] = threading.Event()
        if wait_ev is not None:
            wait_ev.wait(timeout=15.0)
            with self._cache_lock:
                path = self._cache.get(key)
                if path and os.path.exists(path):
                    self._cache.move_to_end(key)
                    return path
            with self._cache_lock:
                my_ev = self._inflight.get(key)
                if my_ev is None:
                    my_ev = self._inflight[key] = threading.Event()
                else:
                    my_ev = None
        import hashlib
        ext = ".wav" if eng == "kokoro" else ".mp3"
        path = os.path.join(self._tmp, hashlib.md5(key.encode()).hexdigest() + ext)
        rate_val = int(self.cfg.get("speech_rate", 8))
        part = f"{path}.{threading.get_ident()}.part"
        try:
            if eng == "kokoro":
                self._synth_kokoro(text, vid, rate_val, part)
            elif eng == "google":
                self._synth_google(text, vid, rate_val, part)
            else:
                self._synth_edge(text, vid, rate_val, part)
            with self._cache_lock:
                existing = self._cache.get(key)
                if existing and os.path.exists(existing):
                    self._cache.move_to_end(key)
                    try:
                        os.remove(part)
                    except Exception:
                        pass
                    return existing
                os.replace(part, path)
                self._cache[key] = path
                evicted = []
                while len(self._cache) > self.CACHE_MAX:
                    _, old = self._cache.popitem(last=False)
                    evicted.append(old)
            for old in evicted:
                try:
                    os.remove(old)
                except Exception:
                    pass
            return path
        finally:
            try:
                if os.path.exists(part):
                    os.remove(part)
            except Exception:
                pass
            with self._cache_lock:
                self._queued_synth.discard(key)
                if my_ev is not None and self._inflight.get(key) is my_ev:
                    del self._inflight[key]
            if my_ev is not None:
                my_ev.set()

    def _synth_worker(self):
        while True:
            text, vname = self.synth_q.get()
            try:
                if self.enabled:
                    self._synth(text, vname)
            except Exception:
                pass

    def _is_cached(self, text, vname=None):
        with self._cache_lock:
            p_ = self._cache.get(self._key(text, vname))
        return bool(p_ and os.path.exists(p_))

    def _synth_wait(self, text, vname, spot):
        """Synthesise on a helper thread while this (playback) thread keeps watching the spotter queue.
        Returns the audio path, or SPOT_FIRST when a spotter call arrived meanwhile (the line is played
        right after it; its synthesis carries on and is cached by then)."""
        if not self.spot_q.empty() and (spot or not self.hold.is_set()):
            return Voice.SPOT_FIRST
        key = self._key(text, vname)
        with self._cache_lock:
            p_ = self._cache.get(key)
            if p_ and os.path.exists(p_):
                self._cache.move_to_end(key)
                self._queued_synth.discard(key)
                return p_
        box = {}
        ev = threading.Event()

        def work():
            try:
                box["path"] = self._synth(text, vname)
            except Exception as e:
                box["err"] = e
            finally:
                ev.set()
                loop = getattr(self._tls, "loop", None)
                if loop is not None:
                    self._tls.loop = None
                    try:
                        loop.close()
                    except Exception:
                        pass
        threading.Thread(target=work, daemon=True, name="synth-now").start()
        while not ev.wait(0.02):
            if not self.spot_q.empty() and (spot or not self.hold.is_set()):
                return Voice.SPOT_FIRST
        if "err" in box:
            raise box["err"]
        return box["path"]

    SPOT_FIRST = object()

    def _speak(self, text, vname=None):
        if not self.enabled or not text:
            return
        spot = bool(self._item and self._item[1] == "spot")
        if spot and not self._is_cached(text, vname):
            short = text.split(",", 1)[0].rstrip(".") + "."
            if short != text and self._is_cached(short, vname):
                self.prefetch(text, vname)
                text = short
        eng, _vid, label = self._resolve_voice(vname or self.cfg.get("voice"))
        if self._mixer:
            try:
                import pygame
                try:
                    path = self._synth_wait(text, vname, spot)
                except Exception as first_err:
                    if eng == "edge":
                        raise
                    note = f"{label} unavailable ({first_err}); falling back to Microsoft neural voice."
                    if note != getattr(self, "_fallback_note", None):
                        self._fallback_note = note
                        self.log(note)
                    path = self._synth_wait(text, "en-GB-RyanNeural", spot)
                    label = "Microsoft neural voice (fallback)"
                if path is Voice.SPOT_FIRST:
                    return Voice.SPOT_FIRST
                if self._stale():
                    if self._item and self._item[1] == "cue":
                        self._drop_cue(text, vname)
                    return
                if self._must_stop(spot):
                    return None if (spot or self._is_chat() or self._cancelled()) else Voice.SPOT_FIRST
                with self._mlock:
                    pygame.mixer.music.load(path)
                    pygame.mixer.music.set_volume(float(self.cfg.get("volume", 0.9)))
                    pygame.mixer.music.play()
                self._started(label)
                cut = False
                while pygame.mixer.music.get_busy():
                    if self._must_stop(spot):
                        pygame.mixer.music.stop()
                        cut = True
                        break
                    time.sleep(0.02)
                with self._mlock:
                    pygame.mixer.music.unload()
                self._last_spoke_end = time.monotonic()
                if cut and self._item and self._item[1] == "urgent" and not self._cancelled():
                    return Voice.SPOT_FIRST
                return
            except Exception as e:
                self.log(f"Voice synthesis unavailable ({e}); using the Windows voice.")
        if self._sapi is not None:
            if self._stale():
                if self._item and self._item[1] == "cue":
                    self._drop_cue(text, vname)
                return
            if self._must_stop(spot):
                return None if (spot or self._is_chat() or self._cancelled()) else Voice.SPOT_FIRST
            try:
                self._started("Windows voice (neural voice unreachable)")
                spot = bool(self._item and self._item[1] == "spot")
                self._sapi.Speak(text, 1)
                while not self._sapi.WaitUntilDone(50):
                    if self._must_stop(spot):
                        self._sapi.Speak("", 3)
                        self._last_spoke_end = time.monotonic()
                        if self._item and self._item[1] == "urgent" and not self._cancelled():
                            return Voice.SPOT_FIRST
                        break
                self._last_spoke_end = time.monotonic()
                return
            except Exception:
                pass
        self._started(None)

    def _is_chat(self):
        return bool(self._item and self._item[1] == "chat")

    def _cancelled(self):
        return bool(self._item and self._item[0] in self._cancel)

    def cancel(self, texts):
        """Drop these lines: from the queue, from lines waiting to resume, and the one playing now (it stops and
        isn't resumed). Returns how many were dropped. Used by "skip the briefing"."""
        texts = {t for t in texts if t}
        if not texts:
            return 0
        n, span = 0, 0.0
        with self.q.mutex:
            keep = [it for it in self.q.queue if it[0] not in texts]
            for it in self.q.queue:
                if it[0] in texts:
                    span += self.duration(it[0]) + self.latency(it[0], it[3]) + GAP_AFTER_TALK
            n += len(self.q.queue) - len(keep)
            self.q.queue.clear()
            self.q.queue.extend(keep)
        for lst in (self._resumes, self._deferred):
            before = len(lst)
            lst[:] = [it for it in lst if it[0] not in texts]
            n += before - len(lst)
        self._cancel = texts
        if self._item and self._item[0] in texts:
            n += 1
        self.busy_until = max(self._last_spoke_end + GAP_AFTER_TALK, self.busy_until - span)
        return n

    def _must_stop(self, spot):
        """Stop (or don't start) the current line: push-to-talk is held, a spotter call is waiting, or this is crew
        banter and an urgent call (box, flags, damage...) is queued behind it: banter never holds those up.
        A line cancelled by "skip the briefing" stops too."""
        if self._cancelled():
            return True
        if self.hold.is_set():
            return True
        if spot:
            return not self.spot_q.empty()
        if self.preempt.is_set() or not self.spot_q.empty():
            return True
        if self._is_chat():
            with self.q.mutex:
                return any(it[1] == "urgent" for it in self.q.queue)
        return False

    def _stale(self):
        """Too late to say: a corner cue more than a second old (the corner has gone), or a spotter call more
        than 1.5 s old or while push-to-talk is held."""
        it = self._item
        if not it:
            return False
        if it[1] == "cue":
            return time.monotonic() - it[2] > 1.0
        if it[1] == "spot":
            return time.monotonic() - it[2] > 1.5 or self.hold.is_set() or not self.spot_q.empty()
        return False

    def _take_urgent(self):
        """The oldest queued 'urgent' line, taken out of the FIFO ahead of routine speech (None if none)."""
        q = self.q
        with q.mutex:
            for i, it in enumerate(q.queue):
                if it[1] == "urgent":
                    del q.queue[i]
                    q.not_full.notify()
                    return it
        return None

    def _drop_cue(self, text, vname):
        span = self.duration(text) + self.latency(text, vname) + GAP_AFTER_TALK
        floor = self._last_spoke_end + GAP_AFTER_TALK
        empty = self.q.empty() and not self._resumes and not self._deferred
        self.busy_until = floor if empty else max(floor, self.busy_until - span)

    def _done_speaking(self):
        """After a line finishes or is cut off, nothing queued: the radio is free a moment later."""
        if self.enabled and self.q.empty() and not self._resumes and not self._deferred:
            self.busy_until = min(self.busy_until, self._last_spoke_end + GAP_AFTER_TALK)

    def _started(self, engine):
        if self.events is None or self._item is None:
            return
        text, kind, created = self._item[:3]
        try:
            self.events(rc_t=time.monotonic(), rc_voice=(engine, time.monotonic() - created, kind, text))
        except Exception:
            pass

    def _run(self):
        self._init_audio()
        deferred, resumes = self._deferred, self._resumes
        while True:
            try:
                item = self.spot_q.get_nowait()
            except queue.Empty:
                if resumes and resumes[0][1] == "urgent":
                    item = None
                else:
                    item = self._take_urgent()
                if item is None and resumes:
                    item = resumes.pop(0)
                    while self.hold.is_set():
                        time.sleep(0.05)
                    self._item = item
                    if self._speak(item[0], item[3]) is Voice.SPOT_FIRST:
                        resumes.insert(0, item)
                    else:
                        self._done_speaking()
                    continue
                if item is None and deferred and not self.hold.is_set() and (
                        self.on_straight.is_set() or time.monotonic() - deferred[0][2] > 20):
                    self._item = deferred.pop(0)
                    if self._speak(self._item[0], self._item[3]) is Voice.SPOT_FIRST:
                        resumes.insert(0, self._item)
                    else:
                        self._done_speaking()
                    continue
                if item is None:
                    try:
                        item = self.q.get(timeout=0.05)
                    except queue.Empty:
                        pass
            if item:
                text, kind, created, vname = item
                if kind == "__reinit__":
                    self._init_audio()
                    continue
                if kind == "spot":
                    while True:
                        try:
                            item = self.spot_q.get_nowait()
                        except queue.Empty:
                            break
                    text, kind, created, vname = item
                    self.preempt.clear()
                    if time.monotonic() - created < 1.5 and not self.hold.is_set():
                        self._item = item
                        self._speak(text, vname)
                    continue
                if kind == "cue" and time.monotonic() - created > 1.0:
                    self._drop_cue(text, vname)
                    continue
                if kind == "answer" and not self.on_straight.is_set() and len(text.split()) > 12:
                    deferred.append(item)
                    continue
                while self.hold.is_set():
                    time.sleep(0.05)
                self._item = item
                if self._speak(text, vname) is Voice.SPOT_FIRST:
                    resumes.insert(0, item)
                    continue
                self._done_speaking()




BUTTON_ACTIONS = [("ptt", "Push-to-talk (hold)"), ("repeat", "Repeat last message"),
                  ("mute", "Mute / unmute coach"), ("tones", "Braking tones on / off"),
                  ("overlay", "Show / hide overlay"), ("capture", "Start / stop a data capture"),
                  ("sheet", "Show / hide the setup sheet")]


class Controls:
    """Polls wheel/joystick buttons in one background thread (pygame), works while the game has focus.
    Bindings live in cfg["buttons"][action] = {"device", "guid", "index", "button"}."""

    def __init__(self, cfg, log=print):
        self.cfg, self.log = cfg, log
        self.handlers = {}
        self.held = set()
        self.devices = []
        self.ok = False
        self._capture = None
        self._lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True, name="wheel-buttons").start()

    def on(self, action, cb):
        self.handlers[action] = cb

    def is_held(self, action):
        return action in self.held

    def describe(self, action):
        b = self.cfg.get("buttons", {}).get(action)
        if not b:
            return "Not set"
        return f"{b['device']}  ·  btn {b['button'] + 1}"

    def capture(self, cb, timeout=20):
        """Call cb(binding_dict or None) with the next button pressed on any device."""
        with self._lock:
            self._capture = (cb, time.monotonic() + timeout)

    def bind(self, action, binding):
        with _CFG_LOCK:
            self.cfg.setdefault("buttons", {})
            if binding is None:
                self.cfg["buttons"].pop(action, None)
            else:
                for other, b in list(self.cfg["buttons"].items()):
                    if other != action and b.get("guid") == binding["guid"] and b.get("index") == binding["index"] \
                            and b["button"] == binding["button"]:
                        self.cfg["buttons"].pop(other)
                self.cfg["buttons"][action] = binding
            save_config(self.cfg)

    def _scan(self, pygame):
        pygame.joystick.quit()
        pygame.joystick.init()
        seen, devs = {}, []
        for i in range(pygame.joystick.get_count()):
            j = pygame.joystick.Joystick(i)
            j.init()
            guid = j.get_guid() if hasattr(j, "get_guid") else j.get_name()
            n = seen.get(guid, 0)
            seen[guid] = n + 1
            devs.append((j, j.get_name(), guid, n))
        self.devices = devs
        self.log("Controllers: " + (", ".join(d[1] for d in devs) or "none found"))

    def _find(self, b):
        for j, name, guid, idx in self.devices:
            if b.get("guid") and guid == b["guid"] and idx == b.get("index", 0):
                return j
        for j, name, guid, idx in self.devices:
            if name == b.get("device"):
                return j
        return None

    def _run(self):
        try:
            import pygame
            pygame.init()
            pygame.joystick.init()
            self._scan(pygame)
            self.ok = True
        except Exception as e:
            self.log(f"Wheel buttons unavailable: {e}")
            return
        prev, base, last_scan = {}, None, time.monotonic()
        while True:
            try:
                pygame.event.pump()
                now = time.monotonic()
                if now - last_scan > 3:
                    last_scan = now
                    if pygame.joystick.get_count() != len(self.devices):
                        self._scan(pygame)
                        prev, base = {}, None
                with self._lock:
                    cap = self._capture
                if cap is not None:
                    cb, deadline = cap
                    if base is None:
                        base = {id(j): [j.get_button(k) for k in range(j.get_numbuttons())] for j, *_ in self.devices}
                    hit = None
                    for j, name, guid, idx in self.devices:
                        for k in range(j.get_numbuttons()):
                            if j.get_button(k) and not base.get(id(j), [0] * (k + 1))[k]:
                                hit = {"device": name, "guid": guid, "index": idx, "button": k}
                                break
                        if hit:
                            break
                    if hit or now > deadline:
                        with self._lock:
                            self._capture = None
                        base = None
                        try:
                            cb(hit)
                        except Exception as e:
                            self.log(f"Binding error: {e}")
                    time.sleep(0.01)
                    continue
                held = set()
                for action, b in list(self.cfg.get("buttons", {}).items()):
                    j = self._find(b)
                    if j is None or b["button"] >= j.get_numbuttons():
                        continue
                    down = bool(j.get_button(b["button"]))
                    if down:
                        held.add(action)
                        if not prev.get(action) and action in self.handlers:
                            try:
                                self.handlers[action]()
                            except Exception as e:
                                self.log(f"Button action error: {e}")
                    prev[action] = down
                self.held = held
            except Exception as e:
                if not getattr(self, "_poll_err_said", False):
                    self._poll_err_said = True
                    self.log(f"Wheel button polling error: {e} (recovering)")
                try:
                    if "not initialized" in str(e):
                        pygame.display.init()
                        pygame.joystick.init()
                        self._scan(pygame)
                        prev, base = {}, None
                except Exception:
                    pass
                time.sleep(1)
            time.sleep(0.01)




HALLUCINATIONS = {"", "you", "thank you", "thanks for watching", "bye", ".", "thank you.", "you.",
                  "thanks.", "okay.", "so"}
WHISPER_PROMPT = ("Sim racing team radio. Turn, braking point, apex, throttle, lap time, delta, fuel, tyres, "
                  "understeer, oversteer, setup, race setup, pit window, box this lap, debrief, repeat, quiet, report, theoretical best.")
STT_KEYWORDS = ["braking point", "apex", "trail braking", "understeer", "oversteer", "theoretical best",
                "delta", "tyres", "setup", "race setup", "pit window", "box this lap", "debrief", "repeat",
                "quiet", "talk more", "reset reference", "braking tones", "split deltas", "report", "fuel"]


def _mme_hostapi(sd):
    try:
        return next((i for i, a in enumerate(sd.query_hostapis()) if "MME" in a["name"]), None)
    except Exception:
        return None


def list_input_devices():
    """Microphone names (Windows MME list, which accepts any sample rate)."""
    try:
        import sounddevice as sd
        mme = _mme_hostapi(sd)
        return [d["name"] for d in sd.query_devices()
                if d["max_input_channels"] > 0 and (mme is None or d["hostapi"] == mme)]
    except Exception:
        return []


def _input_index(name):
    if not name:
        return None
    try:
        import sounddevice as sd
        mme = _mme_hostapi(sd)
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and d["name"] == name and (mme is None or d["hostapi"] == mme):
                return i
    except Exception:
        pass
    return None


class Listener:
    """Push-to-talk from a wheel button, the on-screen button or the keyboard fallback key;
    records the chosen mic and transcribes offline with faster-whisper (English model + voice-activity
    filter) or online with OpenAI (falls back to offline if OpenAI can't be reached)."""

    def __init__(self, cfg, voice: Voice, controls, on_text, log=print, events=None):
        self.cfg, self.voice, self.controls, self.on_text, self.log = cfg, voice, controls, on_text, log
        self.events = events
        self.level = self.peak = 0.0
        self.model_name = cfg.get("whisper_model", "small.en")
        self.gui_ptt = threading.Event()
        self.stop = threading.Event()
        self._online_off_until = 0.0
        self.state = "starting"
        threading.Thread(target=self._run, daemon=True, name="listener").start()

    def _key(self):
        return (self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
                or DEFAULT_CONFIG["openai_api_key"] or "").strip()

    def _local_model(self):
        """Offline faster-whisper model (also the fallback when OpenAI can't be reached)."""
        name = self.model_name if self.model_name != "openai" else "small.en"
        try:
            from faster_whisper import WhisperModel
            self.log(f"Loading speech model {name} (first run downloads it)...")
            return WhisperModel(name, device="cpu", compute_type="int8",
                                cpu_threads=min(2, max(1, (os.cpu_count() or 4) // 4)))
        except Exception as e:
            self.log(f"Speech model failed to load: {e}")
            return None

    def _transcribe_openai(self, audio):
        """Send the push-to-talk clip (16 kHz mono) to OpenAI as a WAV and return the text."""
        import io
        import wave
        import numpy as np
        import openai
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm)
        client = openai_client(self._key()).with_options(timeout=6.0, max_retries=0)
        kw = {"model": self.cfg.get("openai_stt_model") or "gpt-transcribe",
              "file": ("ptt.wav", buf.getvalue(), "audio/wav"), "prompt": WHISPER_PROMPT}
        try:
            r = client.audio.transcriptions.create(**kw, extra_body={"languages": ["en"], "keywords": STT_KEYWORDS})
        except openai.BadRequestError:
            r = client.audio.transcriptions.create(**kw, language="en")
        return (getattr(r, "text", "") or "").strip()

    def _held(self, kb):
        if self.gui_ptt.is_set() or (self.controls is not None and self.controls.is_held("ptt")):
            return True
        if kb is not None:
            try:
                return kb.is_pressed(self.cfg.get("ptt_key") or "f8")
            except Exception:
                return False
        return False

    def _run(self):
        try:
            import numpy as np
            import sounddevice as sd
        except Exception as e:
            self.state = "error"
            self.log(f"Microphone unavailable: {e}")
            return
        try:
            import keyboard as kb
        except Exception:
            kb = None
        model = None
        if self.model_name == "openai":
            if self._key():
                self.log("Speech recognition: OpenAI (online). Hold push-to-talk and speak.")
            else:
                self.log("Speech recognition is set to OpenAI but there's no API key; using the offline model.")
        if self.model_name != "openai" or not self._key():
            model = self._local_model()
            if model is None:
                self.state = "error"
                return
            self.log("Speech recognition ready. Hold push-to-talk and speak.")
        self.state = "ready"
        while not self.stop.is_set():
            if not self._held(kb):
                time.sleep(0.02)
                continue
            self.voice.hold.set()
            self.state = "listening"
            self.level = self.peak = 0.0
            self._event(rc_ptt=True)
            chunks = []

            def on_audio(d, _frames, _t, _status):
                chunks.append(d.copy())
                lv = float(max(-d.min(), d.max())) if len(d) else 0.0
                self.level = lv
                if lv > self.peak:
                    self.peak = lv

            t0 = time.monotonic()
            mic_error = None
            try:
                with sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                                    device=_input_index(self.cfg.get("mic")), callback=on_audio):
                    while self._held(kb) and time.monotonic() - t0 < 15:
                        time.sleep(0.02)
            except Exception as e:
                mic_error = str(e)
                self.log(f"Microphone error: {e}")
                while self._held(kb):
                    time.sleep(0.05)
            finally:
                self.voice.hold.clear()
                self.state = "ready"
                self.level = 0.0
                self._event(rc_ptt=False, rc_clip_s=time.monotonic() - t0)
            if mic_error:
                self._event(rc_fail=("mic", f"Microphone error: {mic_error[:90]}"))
                continue
            if not chunks:
                self._event(rc_fail=("mic", "No sound came from the microphone. Check it in Settings."))
                continue
            audio = np.concatenate(chunks)[:, 0]
            if len(audio) < 16000 * 0.4:
                self._event(rc_fail=("mic", "Too short. Keep holding the button while you speak."))
                continue
            if self.peak < 0.01:
                self._event(rc_fail=("mic", "Too quiet. Wrong microphone, or it's muted? Check Settings."))
                continue
            self._event(rc_mic=round(self.peak * 100))
            text, engine, t1 = None, None, time.monotonic()
            if self.model_name == "openai" and self._key() and time.monotonic() >= self._online_off_until:
                try:
                    text, engine = self._transcribe_openai(audio), "OpenAI"
                except Exception as e:
                    self._online_off_until = time.monotonic() + 120
                    self.log(f"OpenAI speech recognition failed ({type(e).__name__}: {e}). "
                             "Using the offline model for the next 2 minutes.")
            if text is None:
                model = model or self._local_model()
                if model is None:
                    self._event(rc_fail=("stt", "Speech model failed to load (see Log)."))
                    continue
                try:
                    segs, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=True,
                                               condition_on_previous_text=False, no_speech_threshold=0.6,
                                               initial_prompt=WHISPER_PROMPT)
                    text = " ".join(s.text for s in segs).strip()
                    engine = "Offline " + (self.model_name if self.model_name != "openai" else "small.en")
                except Exception as e:
                    self.log(f"Transcription failed: {e}")
                    self._event(rc_fail=("stt", f"Transcription failed: {str(e)[:80]}"))
                    continue
            if text.lower().strip(" .!?") in HALLUCINATIONS or (len(text) > 25 and text.strip() in WHISPER_PROMPT):
                self._event(rc_fail=("stt", "Didn't catch any words. Speak a little louder or closer."))
                continue
            self._event(rc_heard=text, rc_stt=f"{engine} · {time.monotonic() - t1:.1f} s")
            self.log(f"DRIVER: {text}")
            try:
                self.on_text(text)
            except Exception as e:
                self.log(f"Couldn't answer that ({type(e).__name__}: {e})")

    def _event(self, **kw):
        if self.events is not None:
            try:
                self.events(rc_t=time.monotonic(), **kw)
            except Exception:
                pass




class Overlay:
    def __init__(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.title("SimCoach")
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#111111")
        self.root.geometry("480x190+40+40")
        self.vars = {k: tk.StringVar(value="") for k in ("head", "delta", "tip", "focus", "heard")}
        self.vars["head"].set("Waiting for a sim...")
        mk = lambda var, fg, font, **kw: tk.Label(self.root, textvariable=self.vars[var], fg=fg, bg="#111111",
                                                  font=font, wraplength=460, justify="left", **kw)
        mk("head", "#9aa0a6", ("Segoe UI", 10)).pack(anchor="w", padx=10, pady=(8, 0))
        self.delta_lbl = mk("delta", "#ffffff", ("Segoe UI Semibold", 26))
        self.delta_lbl.pack(anchor="w", padx=10)
        mk("tip", "#ffd54f", ("Segoe UI", 12)).pack(anchor="w", padx=10)
        mk("focus", "#80cbc4", ("Segoe UI", 10)).pack(anchor="w", padx=10)
        mk("heard", "#b39ddb", ("Segoe UI", 9)).pack(anchor="w", padx=10)
        self.inbox: "queue.Queue[dict]" = queue.Queue()
        self.sheet_win = None
        self.last_sheet = None
        self.root.after(100, self._pump)

    def post(self, **kw):
        self.inbox.put(kw)

    def _sheet(self, kw):
        """The setup-sheet pop-up in console mode: opened, replaced or closed like in the app."""
        open_now = self.sheet_win is not None and self.sheet_win.alive()
        if kw.get("setup_sheet"):
            self.last_sheet = kw["setup_sheet"]
        if kw.get("setup_close") or (kw.get("setup_toggle") and open_now):
            if self.sheet_win is not None:
                self.sheet_win.close()
            self.sheet_win = None
        elif kw.get("setup_sheet") and not kw.get("setup_popup") and open_now and self.sheet_win.sheet is kw.get("setup_sheet"):
            self.sheet_win.sync_from_sheet()
        elif (kw.get("setup_sheet") and kw.get("setup_popup")) or (kw.get("setup_toggle") and self.last_sheet):
            if self.sheet_win is not None:
                self.sheet_win.close()
            try:
                self.sheet_win = SetupSheetWindow(self.root, self.last_sheet, open_file=_open_path)
            except Exception as e:
                self.sheet_win = None
                file_log(f"Couldn't open the setup sheet: {type(e).__name__}: {e}")

    def _pump(self):
        try:
            while True:
                kw = self.inbox.get_nowait()
                if any(k in kw for k in ("setup_sheet", "setup_close", "setup_toggle")):
                    self._sheet(kw)
                for k, v in kw.items():
                    if k == "delta_color":
                        self.delta_lbl.configure(fg=v)
                    elif k in self.vars:
                        self.vars[k].set(v)
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def run(self):
        self.root.mainloop()


class NullOverlay:
    def post(self, **kw):
        pass


def ref_problem(d, need_key=True):
    """None if d is a usable SimCoach reference (as saved or exported), else what's wrong with it."""
    try:
        if not isinstance(d, dict):
            return "not a reference"
        if need_key:
            key = d.get("key")
            if not (isinstance(key, (list, tuple)) and len(key) == 3 and all(isinstance(k, str) and k for k in key)):
                return "missing sim / track / car"
        ref = d.get("ref")
        if not isinstance(ref, dict):
            return "no lap trace"
        for name in ("speed", "thr", "brk", "t") + tuple(k for k in ("steer", "lock", "spin", "overlap") if k in ref):
            a = ref.get(name)
            if not isinstance(a, list) or len(a) != BINS:
                return f"the {name} trace is the wrong length"
            if not all(type(x) in (int, float) and not math.isinf(x) for x in a):
                return f"the {name} trace isn't numeric"
        corners = d.get("corners")
        if not isinstance(corners, list):
            return "no corner list"
        for c in corners:
            if not (isinstance(c, (list, tuple)) and len(c) == 3
                    and all(type(x) is int and 0 <= x < BINS for x in c) and c[0] <= c[1] <= c[2]):
                return "a corner is out of range"
        bc = d.get("best_corner")
        if not isinstance(bc, dict) or not all(isinstance(v, dict) for v in bc.values())                 or {int(k) for k in bc} != set(range(len(corners))) or len(bc) != len(corners):
            return "corner records don't match the corners"
        for v in bc.values():
            for k in ("min_speed", "peak_brake", "trail", "coast", "lock", "spin", "overlap", "corrections"):
                if k in v and (type(v[k]) not in (int, float, bool) or not math.isfinite(v[k])):
                    return "a corner record isn't numeric"
            for k in ("bp", "tp"):
                if v.get(k) is not None and (type(v[k]) not in (int, float) or not (0 <= v[k] < BINS)):
                    return "a corner record isn't numeric"
            if "seg" in v and v["seg"] is None:
                return "a corner time isn't a real duration"
            seg = v.get("seg")
            if seg is not None and not (type(seg) in (int, float) and (seg != seg or (math.isfinite(seg) and seg >= 0))):
                return "a corner time isn't a real duration"
        bt = d.get("best_time")
        if not (type(bt) in (int, float) and math.isfinite(bt) and bt > 0):
            return "bad lap time"
    except Exception as e:
        return f"unreadable ({e})"
    return None


def _observed(seen, lo: int, hi: int) -> bool:
    """Telemetry really covered bins lo..hi (seen: a lap's mask of bins that got a frame): there are samples at
    (or just beyond) both ends and no long gap between them, so filled() interpolated this stretch rather than
    extrapolating it. Works at any sample rate (at 10-20 Hz a fast car skips several bins between frames)."""
    g = max(8, BINS // 100)
    idx = [k for k in range(max(0, lo - g), min(BINS - 1, hi + g) + 1) if seen[k]]
    if not idx or idx[0] > lo + 2 or idx[-1] < hi - 2:
        return False
    return all(b - a <= g for a, b in zip(idx, idx[1:]))


def _corner_window(c):
    return max(0, c[0] - _W0_PAD), min(BINS - 1, c[2] + _W1_PAD)


class PedalMeter:
    """Live pedal pressure versus your reference lap at the same spot on track, for the overlay gauges.

    For each pedal the target is the range of pressure the reference lap used within about 12 m of where you
    are now (so braking a few metres earlier or later isn't flagged). Verdicts: 'much' (above that range, or
    locking / wheelspin), 'little' (below it), 'enough' (inside it), 'idle' (off the pedal where the
    reference was too), 'none' (no reference yet). A verdict must hold for 3 updates before it shows,
    so it doesn't flicker; lock-ups and wheelspin show at once. Runs on the GUI thread (~30 Hz), reading the
    coach's latest frame: nothing is added to the 60 Hz telemetry loop."""

    TOL = 0.10
    WINDOW_M = 12.0
    HOLD = 3

    def __init__(self, history=120):
        self.hist = deque(maxlen=history)
        self._shown = {"thr": "none", "brk": "none"}
        self._cand = {"thr": ("none", 0), "brk": ("none", 0)}
        self._last_frame = None

    @staticmethod
    def _clamp(x):
        return 0.0 if x != x or x < 0.0 else 1.0 if x > 1.0 else x

    def _decide(self, key, raw, instant):
        cand, n = self._cand[key]
        n = n + 1 if raw == cand else 1
        self._cand[key] = (raw, n)
        if instant or n >= self.HOLD or self._shown[key] == "none":
            self._shown[key] = raw
        return self._shown[key]

    def update(self, f, ref, track_len=None):
        """Returns {'thr': {...}, 'brk': {...}} or None when there is no new frame."""
        if f is None or f is self._last_frame:
            return None
        self._last_frame = f
        thr, brk = self._clamp(f.throttle), self._clamp(f.brake)
        p = f.pct
        i = 0 if (p != p or p <= 0.0) else BINS - 1 if p >= 1.0 else int(p * BINS)
        lock = spin = False
        wk, spd = f.wheel_kmh, f.speed
        if wk is not None and spd > 40:
            fr_min = wk[0] if wk[0] < wk[1] else wk[1]
            rr_min = wk[2] if wk[2] < wk[3] else wk[3]
            rr_max = wk[2] if wk[2] > wk[3] else wk[3]
            lock = brk > 0.3 and (fr_min < 0.75 * spd or (rr_min < 0.75 * spd and f.game not in RALLY_GAMES))
            spin = thr > 0.4 and rr_max > 1.12 * spd + 4
        out = {}
        r_thr = r_brk = None
        w = max(2, int(BINS * self.WINDOW_M / (track_len or 4000.0)))
        lo_i, hi_i = i - w, i + w + 1
        for key, val, flag in (("thr", thr, "spin" if spin else None), ("brk", brk, "lock" if lock else None)):
            band = None
            if ref:
                arr = ref[key]
                if lo_i < 0:
                    raw = arr[lo_i:] + arr[:hi_i]
                elif hi_i > BINS:
                    raw = arr[lo_i:] + arr[:hi_i - BINS]
                else:
                    raw = arr[lo_i:hi_i]
                seg = [x for x in raw if x == x]
                if seg:
                    band = (min(seg), max(seg))
                rv = ref[key][i]
                if key == "thr":
                    r_thr = rv if rv == rv else None
                else:
                    r_brk = rv if rv == rv else None
            if flag:
                raw = "much"
            elif band is None:
                raw = "none"
            elif val > band[1] + self.TOL:
                raw = "much"
            elif val < band[0] - self.TOL:
                raw = "little"
            elif val < 0.03 and band[1] < 0.05:
                raw = "idle"
            else:
                raw = "enough"
            out[key] = {"value": val, "band": band, "verdict": self._decide(key, raw, flag is not None),
                        "flag": flag}
        self.hist.append((thr, brk, r_thr, r_brk))
        return out




_X_BINS = _np.arange(BINS, dtype=float) if _np is not None else None


def _fill_slice_1d(src, w0, w1, inplace=False):
    """Interpolate NaNs within [w0, w1] only. Fast-path returns `src` directly when [w0, w1] has no NaNs."""
    s = sum(src[w0:w1 + 1])
    if s == s:
        return src
    lo = w0
    while lo >= 0 and src[lo] != src[lo]:
        lo -= 1
    hi = w1
    while hi < BINS and src[hi] != src[hi]:
        hi += 1
    if lo < 0 and hi >= BINS:
        return None
    start = lo if lo >= 0 else w0
    stop = (hi + 1) if hi < BINS else (w1 + 1)
    res = src if (inplace and lo >= 0 and hi < BINS) else list(src)
    prev = first = -1
    for k in range(start, stop):
        v = src[k]
        if v == v:
            if first < 0:
                first = k
            if prev >= 0 and k - prev > 1:
                va = src[prev]
                dv = (v - va) / (k - prev)
                for m in range(max(prev + 1, w0), min(k, w1 + 1)):
                    res[m] = va + dv * (m - prev)
            prev = k
    if first < 0:
        return None
    if first > w0:
        v0 = src[first]
        for m in range(w0, min(first, w1 + 1)):
            res[m] = v0
    if prev < w1:
        v1 = src[prev]
        for m in range(max(prev + 1, w0), w1 + 1):
            res[m] = v1
    return res


_INV_BACK = 20


class Lap:
    def __init__(self):
        n = math.nan
        self.speed, self.thr, self.brk, self.t = [n] * BINS, [n] * BINS, [n] * BINS, [n] * BINS
        self.seen = bytearray(BINS)
        self.invalid = self.pit = False
        self.max_temp = self.min_temp = None
        self.fuel_start = self.fuel_end = None
        self.lock, self.spin, self.overlap = [0] * BINS, [0] * BINS, [0] * BINS
        self.steer = [math.nan] * BINS
        self.shift_ratios = []
        self.limiter_time = 0.0
        self.max_press = self.min_press = None
        self.ctx_yellow = False          # a yellow / safety car at any point in the lap
        self.ctx_traffic_s = 0.0         # seconds spent right behind or alongside another car
        self._prev_gear = None
        self._prev_rpm = 0.0
        self._prev_t = None
        self._t_hi = -1.0
        self._valid_t = 0
        self._t_backwards = False
        self.rewound = False
        self._min_bin = BINS
        self._max_bin = -1
        self._prev_bin = None
        self._max_gap = 0
        self._samples = 0
        self._mono_first = None
        self._mono_last = None
        self.off_bins = []
        self._inv_bins = set()

    def add(self, f: Frame):
        pct = f.pct
        i = int(pct * BINS)
        if i >= BINS:
            i = BINS - 1
        elif i < 0:
            i = 0
        now_m = time.monotonic()
        if self._mono_first is None:
            self._mono_first = now_m
        self._mono_last = now_m
        t = f.cur_time
        if t + 0.5 < self._t_hi:
            rewind = (t > 0.2 and self._prev_bin is not None and i < self._prev_bin and self._valid_t >= 3)
            near_start = (not rewind and self._valid_t < BINS // 8 and pct < 0.15)
            if near_start or rewind:
                if rewind:
                    self.rewound = True
                    if not f.in_pit:
                        self.pit = False
                nan = math.nan
                limit = t if rewind else t + 0.5
                t_arr = self.t
                valid = 0
                min_b, max_b, prev_b, max_g = BINS, -1, None, 0
                for idx_k, v in enumerate(t_arr):
                    if v == v:
                        if not self.seen[idx_k] or v > limit or (rewind and idx_k > i):
                            t_arr[idx_k] = self.speed[idx_k] = self.thr[idx_k] = self.brk[idx_k] = self.steer[idx_k] = nan
                            self.seen[idx_k] = 0
                            self.lock[idx_k] = self.spin[idx_k] = self.overlap[idx_k] = 0
                        else:
                            valid += 1
                            if idx_k < min_b:
                                min_b = idx_k
                            if idx_k > max_b:
                                max_b = idx_k
                            if prev_b is not None and idx_k - prev_b > max_g:
                                max_g = idx_k - prev_b
                            prev_b = idx_k
                self._valid_t = valid
                self._samples = valid
                self._min_bin, self._max_bin, self._prev_bin, self._max_gap = min_b, max_b, prev_b, max_g
                self._t_hi = t
                if self.off_bins:
                    drop = self._inv_bins if (rewind and not f.lap_invalid and not f.off_track) else ()
                    self.off_bins = [b for b in self.off_bins if t_arr[b] == t_arr[b] and b not in drop]
                    if drop:
                        self._inv_bins.clear()
                    self.invalid = bool(self.off_bins)
            else:
                return
        elif t > self._t_hi:
            self._t_hi = t
        self._samples += 1
        if i < self._min_bin:
            self._min_bin = i
        if i > self._max_bin:
            self._max_bin = i
        if self._prev_bin is not None:
            gap = i - self._prev_bin
            if gap > self._max_gap:
                self._max_gap = gap
        self._prev_bin = i
        if not self.seen[i]:
            self._valid_t += 1
        spd, thr, brk = f.speed, f.throttle, f.brake
        self.speed[i], self.thr[i], self.brk[i], self.t[i] = spd, thr, brk, t
        self.seen[i] = 1
        self.steer[i] = f.steer
        wk = f.wheel_kmh
        if wk is not None and spd > 40:
            w0, w1, w2, w3 = wk
            fr = w0 if w0 < w1 else w1
            rr_min = w2 if w2 < w3 else w3
            rr_max = w2 if w2 > w3 else w3
            lock_thresh = 0.75 * spd
            rear_locked = rr_min < lock_thresh and f.game not in RALLY_GAMES
            if brk > 0.3 and (fr < lock_thresh or rear_locked):
                self.lock[i] = 1 if fr < lock_thresh else 2
            if thr > 0.4 and rr_max > 1.12 * spd + 4:
                self.spin[i] = 1
        if thr > 0.2 and brk > 0.2:
            self.overlap[i] = 1
        max_rpm = f.max_rpm
        if max_rpm > 1000:
            if self._prev_gear is not None and f.gear == self._prev_gear + 1 and f.gear >= 2 and thr > 0.9:
                self.shift_ratios.append(self._prev_rpm / max_rpm)
            if self._prev_t is not None and f.rpm > 0.985 * max_rpm and thr > 0.9:
                dt = t - self._prev_t
                if dt > 0.0:
                    self.limiter_time += 0.1 if dt > 0.1 else dt
        self._prev_gear, self._prev_rpm, self._prev_t = f.gear, f.rpm, t
        tp = f.tyre_press
        if tp is not None and spd > 80:
            hi, lo = max(tp), min(tp)
            if self.max_press is None or hi > self.max_press:
                self.max_press = hi
            if self.min_press is None or lo < self.min_press:
                self.min_press = lo
        if f.off_track:
            self.invalid = True
            ob = self.off_bins
            if not ob or i > ob[-1]:
                ob.append(i)
            elif i != ob[-1]:
                pos = bisect_left(ob, i)
                if pos == len(ob) or ob[pos] != i:
                    ob.insert(pos, i)
        elif f.lap_invalid and not self.invalid:
            self.invalid = True
            ob = self.off_bins
            for b in range(max(0, i - _INV_BACK), i + 1):
                pos = bisect_left(ob, b)
                if pos == len(ob) or ob[pos] != b:
                    ob.insert(pos, b)
                    self._inv_bins.add(b)
        if f.in_pit and spd > 10:
            self.pit = True
        if self.fuel_start is None:
            self.fuel_start = f.fuel
        self.fuel_end = f.fuel
        tt = f.tyre_temps
        if tt is not None:
            hi, lo = max(tt), min(tt)
            if self.max_temp is None or hi > self.max_temp:
                self.max_temp = hi
            if spd > 80 and (self.min_temp is None or lo < self.min_temp):
                self.min_temp = lo

    def has_off_in(self, lo: int, hi: int) -> bool:
        """O(log K) check whether any off-track bin lies within [lo, hi]."""
        ob = self.off_bins
        if not ob:
            return False
        pos = bisect_left(ob, lo)
        return pos < len(ob) and ob[pos] <= hi

    def observed(self, lo: int, hi: int) -> bool:
        return _observed(self.seen, lo, hi)

    def coverage(self):
        raw = self._valid_t / BINS
        if self._samples >= 45 and self._max_bin > self._min_bin and self._max_gap <= int(0.20 * BINS):
            span = (self._max_bin - self._min_bin + 1) / BINS
            return max(raw, span)
        return raw

    def wall_time(self):
        if self._mono_first is not None and self._mono_last is not None:
            return max(0.0, self._mono_last - self._mono_first)
        return 0.0

    def filled_window(self, w0, w1):
        """Fast local interpolation over [w0, w1] for mid-lap corner exit evaluation."""
        s_spd = sum(self.speed[w0:w1 + 1])
        s_t = s_spd if not self._t_backwards else sum(self.t[w0:w1 + 1])
        if s_spd == s_spd and s_t == s_t:
            return {"speed": self.speed, "thr": self.thr, "brk": self.brk, "t": self.t,
                    "lock": self.lock, "spin": self.spin, "overlap": self.overlap, "steer": self.steer}
        inplace = (w1 <= self._max_bin and not self._t_backwards)
        out = {}
        for name in ("speed", "thr", "brk", "t", "steer"):
            r = _fill_slice_1d(getattr(self, name), w0, w1, inplace=inplace)
            if r is None:
                return None
            out[name] = r
        out["lock"], out["spin"], out["overlap"] = self.lock, self.spin, self.overlap
        return out

    def filled(self):
        np = _np
        if np is not None:
            a_spd = np.asarray(self.speed, dtype=float)
            idx = np.flatnonzero(~np.isnan(a_spd))
            if not len(idx):
                return None
            a_t = np.asarray(self.t, dtype=float)
            x = _X_BINS
            idx_f = idx.astype(float)
            if not self._t_backwards:
                idx_t, idx_tf = idx, idx_f
            else:
                idx_t = np.flatnonzero(~np.isnan(a_t))
                if not len(idx_t):
                    return None
                idx_tf = idx_t.astype(float)
            out = {
                "speed": np.interp(x, idx_f, a_spd[idx]).tolist(),
                "thr": np.interp(x, idx_f, np.asarray(self.thr, dtype=float)[idx]).tolist(),
                "brk": np.interp(x, idx_f, np.asarray(self.brk, dtype=float)[idx]).tolist(),
                "t": np.interp(x, idx_tf, a_t[idx_t]).tolist(),
                "steer": np.interp(x, idx_f, np.asarray(self.steer, dtype=float)[idx]).tolist(),
                "lock": self.lock, "spin": self.spin, "overlap": self.overlap,
            }
            return out
        out = {}
        for name in ("speed", "thr", "brk", "t", "steer"):
            arr = list(getattr(self, name))
            idx = [i for i, v in enumerate(arr) if v == v]
            if not idx:
                return None
            for a, b in zip(idx, idx[1:]):
                if b - a > 1:
                    va = arr[a]
                    dv = (arr[b] - va) / (b - a)
                    for k in range(a + 1, b):
                        arr[k] = va + dv * (k - a)
            for k in range(idx[0]):
                arr[k] = arr[idx[0]]
            for k in range(idx[-1] + 1, BINS):
                arr[k] = arr[idx[-1]]
            out[name] = arr
        out["lock"], out["spin"], out["overlap"] = self.lock, self.spin, self.overlap
        return out


def find_corners(ref):
    spd, brk, thr = ref["speed"], ref["brk"], ref["thr"]
    zones, i = [], 0
    while i < BINS:
        if brk[i] > 0.15 or (thr[i] < 0.5 and spd[i] > 60):
            j = i
            while j < BINS and (brk[j] > 0.05 or thr[j] < 0.8):
                j += 1
            zones.append([i, j])
            i = j
        i += 1
    merged = []
    gap_bins = int(0.004 * BINS)
    for z in zones:
        if merged and z[0] - merged[-1][1] < gap_bins:
            merged[-1][1] = z[1]
        else:
            merged.append(z)
    corners = []
    min_ex_offset = int(0.002 * BINS)
    for s, e in merged:
        e = min(BINS - 1, max(e, s + 5))
        seg_spd = spd[s:e + 1]
        v_apex = min(seg_spd)
        apex = s + seg_spd.index(v_apex)
        drop = max(spd[s:apex + 1]) - v_apex if apex > s else 0
        if drop < 6 and max(brk[s:e + 1]) < 0.15:
            continue
        ex = apex
        while ex < BINS - 1 and thr[ex] < 0.95:
            ex += 1
        corners.append((s, apex, min(BINS - 1, max(ex, apex + min_ex_offset))))
    return corners


# --- starter laps: an approximate reference from the track's shape, so coaching starts on lap one --------------
# Track shapes: TUMFTM racetrack-database (github.com/TUMFTM/racetrack-database, LGPL-3.0), race lines computed from
# OpenStreetMap centre lines (c) OpenStreetMap contributors. Rebuild with tools/references/make_starter_laps.py.
STARTER_TRACKS = {   # data name: (spoken name, phrases matched against the sim's track name)
    "Austin": ("Circuit of the Americas", ("austin", "cota", "americas", "texas")),
    "BrandsHatch": ("Brands Hatch", ("brands",)),
    "Budapest": ("the Hungaroring", ("hungaroring", "budapest", "hungary")),
    "Catalunya": ("Barcelona", ("catalunya", "barcelona", "catalonia")),
    "Hockenheim": ("Hockenheim", ("hockenheim", "hockenheimring")),
    "Melbourne": ("Albert Park", ("melbourne", "albert park")),
    "MexicoCity": ("Mexico City", ("mexico", "hermanos rodriguez")),
    "Montreal": ("Montreal", ("montreal", "villeneuve")),
    "Monza": ("Monza", ("monza",)),
    "MoscowRaceway": ("Moscow Raceway", ("moscow",)),
    "Norisring": ("the Norisring", ("norisring",)),
    "Nuerburgring": ("the Nürburgring", ("nurburgring", "nuerburgring", "nurburg")),
    "Oschersleben": ("Oschersleben", ("oschersleben",)),
    "Sakhir": ("Bahrain", ("sakhir", "bahrain")),
    "SaoPaulo": ("Interlagos", ("interlagos", "sao paulo", "jose carlos pace", "brazil")),
    "Sepang": ("Sepang", ("sepang", "malaysia")),
    "Shanghai": ("Shanghai", ("shanghai",)),
    "Silverstone": ("Silverstone", ("silverstone",)),
    "Sochi": ("Sochi", ("sochi",)),
    "Spa": ("Spa", ("spa", "francorchamps")),
    "Spielberg": ("the Red Bull Ring", ("red bull ring", "redbull ring", "redbullring", "spielberg", "austria")),
    "Suzuka": ("Suzuka", ("suzuka",)),
    "YasMarina": ("Yas Marina", ("yas marina", "yas", "abu dhabi")),
    "Zandvoort": ("Zandvoort", ("zandvoort",)),
}
STARTER_TRACKS_B64 = (
    "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"
)
# Car classes for the lap simulation (mass kg, power W, drag CdA m2, downforce ClA m2, tyre grip, braking grip).
STARTER_CARS = {
    "gt3": dict(m=1300.0, P=340e3, CdA=1.10, ClA=2.4, mu=1.55, mu_brk=1.45),
    "gt4": dict(m=1450.0, P=300e3, CdA=0.95, ClA=0.9, mu=1.42, mu_brk=1.32),
    "cup": dict(m=1260.0, P=360e3, CdA=0.95, ClA=1.2, mu=1.50, mu_brk=1.42),
    "gte": dict(m=1250.0, P=380e3, CdA=1.05, ClA=3.0, mu=1.60, mu_brk=1.50),
    "proto": dict(m=960.0, P=400e3, CdA=1.20, ClA=4.2, mu=1.60, mu_brk=1.52),
    "f1": dict(m=800.0, P=700e3, CdA=1.45, ClA=5.6, mu=1.70, mu_brk=1.66),
    "formula": dict(m=680.0, P=280e3, CdA=0.95, ClA=3.2, mu=1.62, mu_brk=1.52),
    "road": dict(m=1100.0, P=125e3, CdA=0.70, ClA=0.0, mu=1.10, mu_brk=1.05),
}
_STARTER_CLASS_WORDS = (   # first match wins; a word matches at the start of a word in the car name
    ("f1", ("formula 1", "formula one", "f1 ", "sf2", "mp4", "fw4", "rb1", "red bull racing", "ferrari sf", "w1")),
    ("formula", ("formula", "f2 ", "f3 ", "f4 ", "fr2", "fr3", "regional", "indy", "ir18", "ir 18", "superformula",
                 "tatuus", "open wheel", "single seater")),
    ("proto", ("lmp", "lmh", "lmdh", "hypercar", "dpi", "prototype", "499p", "963", "9x8", "gr010", "v series",
               "oreca", "ligier js", "ginetta g60", "radical", "glickenhaus", "vanwall", "isotta", "bmw m hybrid",
               "cadillac v", "acura arx", "a424", "sc63")),
    ("gt4", ("gt4",)),
    ("road", ("mx 5", "mx5", "miata", "gr86", "gt86", "brz", "civic", "golf", "road", "street", "abarth", "fiat 500",
              "clio", "polo", "kart", "tcr")),
    ("cup", ("cup", "challenge", "trofeo", "carrera")),
    ("gte", ("gte", "gtlm", "rsr", "gt2")),
    ("gt3", ("gt3",)),
)
_STARTER_DATA = None


_STARTER_NAMES = None
# Benchmark lap times by sim and car class (quick, repeatable laps from setup shops, leaderboards and league
# results; times only). Starter laps are tuned to them and the coach quotes them as a target. The library's
# references/benchmarks/laps.json (downloaded to BENCH_PATH) replaces this copy. Rebuilt by
# tools/references/make_benchmarks.py.
BENCH_PATH = os.path.join(APP_DIR, "benchmarks.json")
STARTER_BENCH = json.loads("".join((
    "{\"tracks\":{\"Nordschleife\":{\"spoken\":\"the Nordschleife\",\"phrases\":[\"nordschleife\"],\"length\":20832},\"Nurburgri",
    "ng24h\":{\"spoken\":\"the N\\u00fcrburgring 24 hour layout\",\"phrases\":[\"nordschleife\",\"nurburgring\",\"24h\"],\"lengt",
    "h\":25378},\"LeMans\":{\"spoken\":\"Le Mans\",\"phrases\":[\"le mans\",\"sarthe\"],\"length\":13626},\"RoadAtlanta\":{\"spoken",
    "\":\"Road Atlanta\",\"phrases\":[\"road atlanta\",\"atlanta\"],\"length\":4088},\"Fuji\":{\"spoken\":\"Fuji\",\"phrases\":[\"fuj",
    "i\"],\"length\":4563},\"DaytonaRoad\":{\"spoken\":\"the Daytona road course\",\"phrases\":[\"daytona\"],\"length\":5730},\"J",
    "erez\":{\"spoken\":\"Jerez\",\"phrases\":[\"jerez\"],\"length\":4428},\"Zhuhai\":{\"spoken\":\"Zhuhai\",\"phrases\":[\"zhuhai\"],",
    "\"length\":4319},\"Bathurst\":{\"spoken\":\"Bathurst\",\"phrases\":[\"bathurst\",\"mount panorama\",\"panorama\"],\"length\":6",
    "213},\"SilverstoneNational\":{\"spoken\":\"Silverstone National\",\"phrases\":[\"silverstone\"],\"length\":2639},\"Silver",
    "stone2008\":{\"spoken\":\"the old Silverstone Grand Prix layout\",\"phrases\":[\"silverstone\"],\"length\":5141},\"India",
    "napolisRoad\":{\"spoken\":\"the Indianapolis road course\",\"phrases\":[\"indianapolis\",\"indy\"],\"length\":3925},\"Indi",
    "anapolisGP\":{\"spoken\":\"Indianapolis\",\"phrases\":[\"indianapolis\",\"indy\"],\"length\":4170},\"TheBend\":{\"spoken\":\"T",
    "he Bend\",\"phrases\":[\"the bend\",\"bend motorsport\"],\"length\":7770},\"Motegi\":{\"spoken\":\"Motegi\",\"phrases\":[\"mot",
    "egi\"],\"length\":4801},\"CharlotteRoval\":{\"spoken\":\"the Charlotte Roval\",\"phrases\":[\"charlotte\"],\"length\":3670}",
    ",\"Misano\":{\"spoken\":\"Misano\",\"phrases\":[\"misano\"],\"length\":4226},\"Zolder\":{\"spoken\":\"Zolder\",\"phrases\":[\"zol",
    "der\"],\"length\":4011},\"Donington\":{\"spoken\":\"Donington\",\"phrases\":[\"donington\"],\"length\":4020},\"LagunaSeca\":{",
    "\"spoken\":\"Laguna Seca\",\"phrases\":[\"laguna seca\",\"laguna\"],\"length\":3602},\"OultonPark\":{\"spoken\":\"Oulton Park",
    "\",\"phrases\":[\"oulton\"],\"length\":4307},\"Snetterton\":{\"spoken\":\"Snetterton\",\"phrases\":[\"snetterton\"],\"length\":",
    "4779},\"Valencia\":{\"spoken\":\"Valencia\",\"phrases\":[\"valencia\",\"ricardo tormo\"],\"length\":4005},\"LongBeach\":{\"sp",
    "oken\":\"Long Beach\",\"phrases\":[\"long beach\"],\"length\":3167},\"Sebring\":{\"spoken\":\"Sebring\",\"phrases\":[\"sebring",
    "\"],\"length\":6019},\"MidOhio\":{\"spoken\":\"Mid-Ohio\",\"phrases\":[\"mid ohio\"],\"length\":3634},\"RoadAmerica\":{\"spoke",
    "n\":\"Road America\",\"phrases\":[\"road america\"],\"length\":6515}},\"laps\":[[\"ACC\",\"gt3\",\"Catalunya\",102.782,null,\"",
    "SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"BrandsHatch\",82.5,null,\"SimRacingAlliance D1 reference\"],[\"AC",
    "C\",\"gt3\",\"Austin\",124.607,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"Donington\",85.91,null,\"SimRac",
    "ingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"Budapest\",102.443,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt",
    "3\",\"Imola\",99.949,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"IndianapolisGP\",94.863,null,\"SimRacin",
    "gAlliance D1 reference\"],[\"ACC\",\"gt3\",\"Kyalami\",99.805,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"",
    "LagunaSeca\",81.301,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"Misano\",92.698,null,\"SimRacingAllian",
    "ce D1 reference\"],[\"ACC\",\"gt3\",\"Monza\",106.711,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"Bathurst",
    "\",119.575,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"Nurburgring24h\",490.0,null,\"SimRacingAlliance",
    " D1 reference\"],[\"ACC\",\"gt3\",\"Nuerburgring\",113.255,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"Oul",
    "tonPark\",92.485,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"PaulRicard\",112.906,null,\"SimRacingAlli",
    "ance D1 reference\"],[\"ACC\",\"gt3\",\"Spielberg\",87.629,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"Sil",
    "verstone\",116.848,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"Snetterton\",105.596,null,\"SimRacingAl",
    "liance D1 reference\"],[\"ACC\",\"gt3\",\"Spa\",136.434,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"Suzuka",
    "\",118.666,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"Valencia\",89.735,null,\"SimRacingAlliance D1 r",
    "eference\"],[\"ACC\",\"gt3\",\"WatkinsGlen\",103.244,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"Zandvoort",
    "\",94.706,null,\"SimRacingAlliance D1 reference\"],[\"ACC\",\"gt3\",\"Zolder\",87.578,null,\"SimRacingAlliance D1 refe",
    "rence\"],[\"iRacing\",\"gt3\",\"Montreal\",92.329,null,\"HYMO Setups / Apex Racing Academy / Coach Dave Academy refe",
    "rence\"],[\"iRacing\",\"gt3\",\"TheBend\",173.188,null,\"HYMO Setups / Apex Racing Academy / Coach Dave Academy refe",
    "rence\"],[\"iRacing\",\"gt3\",\"Spielberg\",88.303,null,\"HYMO Setups / Apex Racing Academy / Coach Dave Academy ref",
    "erence\"],[\"iRacing\",\"gt3\",\"Motegi\",109.4,null,\"HYMO Setups / Apex Racing Academy / Coach Dave Academy refere",
    "nce\"],[\"iRacing\",\"gt3\",\"IndianapolisRoad\",82.441,null,\"HYMO Setups / Apex Racing Academy / Coach Dave Academ",
    "y reference\"],[\"iRacing\",\"gt4\",\"CharlotteRoval\",80.841,null,\"HYMO Setups reference\"],[\"iRacing\",\"proto\",\"Cha",
    "rlotteRoval\",70.812,[\"p320\",\"lmp3\"],\"HYMO Setups reference\"],[\"iRacing\",\"proto\",\"Montreal\",83.397,[\"valkyrie",
    "\"],\"HYMO Setups reference\"],[\"iRacing\",\"proto\",\"Montreal\",83.518,[\"arx\"],\"HYMO Setups reference\"],[\"iRacing\"",
    ",\"proto\",\"Montreal\",83.647,[\"963\"],\"HYMO Setups reference\"],[\"iRacing\",\"proto\",\"Montreal\",83.965,[\"499p\"],\"H",
    "YMO Setups reference\"],[\"iRacing\",\"proto\",\"Montreal\",88.416,[\"p217\",\"lmp2\"],\"HYMO Setups reference\"],[\"iRaci",
    "ng\",\"proto\",\"Silverstone2008\",87.084,[\"919\"],\"iRacing track record (Fernando Horta database)\"],[\"iRacing\",\"p",
    "roto\",\"WatkinsGlen\",84.103,[\"919\"],\"iRacing track record (Fernando Horta database)\"],[\"iRacing\",\"proto\",\"Mug",
    "ello\",80.869,[\"919\"],\"iRacing track record (Fernando Horta database)\"],[\"iRacing\",\"proto\",\"SaoPaulo\",75.906,",
    "[\"919\"],\"iRacing track record (Fernando Horta database)\"],[\"iRacing\",\"proto\",\"Monza\",88.594,[\"919\"],\"iRacing",
    " track record (Fernando Horta database)\"],[\"AC\",\"gt3\",\"Nordschleife\",386.232,null,\"Track Titan top lap\"],[\"r",
    "Factor 2\",\"gt3\",\"Monza\",109.094,null,\"league result (Simresults)\"],[\"rFactor 2\",\"gte\",\"MidOhio\",85.398,[\"c6\"",
    "],\"rFactor 2 record (Fernando Horta database)\"],[\"rFactor 2\",\"gte\",\"Sebring\",123.31,[\"c6\"],\"rFactor 2 record",
    " (Fernando Horta database)\"],[\"AMS2\",\"gt3\",\"SaoPaulo\",86.236,null,\"AMS2 leaderboards (GT3 Gen2)\"],[\"AMS2\",\"g",
    "t3\",\"Catalunya\",100.162,null,\"AMS2 leaderboards (GT3 Gen2)\"],[\"AMS2\",\"gt3\",\"Monza\",106.433,null,\"AMS2 leader",
    "boards (GT3 Gen2)\"],[\"AMS2\",\"gt3\",\"Jerez\",95.721,null,\"AMS2 leaderboards (GT3 Gen2)\"],[\"AMS2\",\"gt3\",\"BrandsH",
    "atch\",82.152,null,\"AMS2 leaderboards (GT3 Gen2)\"],[\"AMS2\",\"gt3\",\"DaytonaRoad\",102.303,null,\"AMS2 leaderboard",
    "s (GT3 Gen2)\"],[\"AMS2\",\"formula\",\"RoadAmerica\",109.925,[\"reynard\"],\"AMS2 leaderboard\"],[\"LMU\",\"gt3\",\"Spa\",13",
    "7.732,null,\"LMU leaderboards and race results\"],[\"LMU\",\"gt3\",\"Imola\",102.355,null,\"LMU leaderboards and race",
    " results\"],[\"LMU\",\"gt3\",\"Fuji\",99.981,null,\"LMU leaderboards and race results\"],[\"LMU\",\"gt3\",\"SaoPaulo\",91.0",
    "39,null,\"LMU leaderboards and race results\"],[\"LMU\",\"gt3\",\"LeMans\",233.398,null,\"LMU leaderboards and race r",
    "esults\"],[\"LMU\",\"gt3\",\"Monza\",109.815,null,\"LMU leaderboards and race results\"],[\"LMU\",\"gt3\",\"LongBeach\",80.",
    "969,null,\"LMU leaderboards and race results\"],[\"LMU\",\"gt3\",\"Sakhir\",118.476,null,\"LMU leaderboards and race ",
    "results\"],[\"LMU\",\"proto\",\"LeMans\",202.564,null,\"LMU / WEC reference\"],[\"LMU\",\"proto\",\"Sakhir\",104.586,[\"cadi",
    "llac\",\"v series\"],\"LMU leaderboard\"],[\"F1 25\",\"f1\",\"Spa\",101.749,null,\"F1 24 time trial, top 5 % (SimRacingS",
    "etup)\"],[\"F1 25\",\"f1\",\"Monza\",78.95,null,\"F1 24 time trial, top 5 % (SimRacingSetup)\"],[\"F1 25\",\"f1\",\"Zandvo",
    "ort\",69.1,null,\"F1 24 time trial, top 5 % (SimRacingSetup)\"],[\"*\",\"gt3\",\"Spa\",136.4,null,\"GT3 leaderboards (",
    "sim not recorded)\"],[\"*\",\"gt3\",\"Monza\",106.35,null,\"GT3 leaderboards (sim not recorded)\"],[\"*\",\"gt3\",\"Suzuka",
    "\",117.475,null,\"GT3 leaderboards (sim not recorded)\"],[\"*\",\"gt3\",\"Spielberg\",86.867,null,\"GT3 leaderboards (",
    "sim not recorded)\"],[\"*\",\"gt3\",\"Catalunya\",100.162,null,\"GT3 leaderboards (sim not recorded)\"],[\"*\",\"gt3\",\"S",
    "aoPaulo\",86.236,null,\"GT3 leaderboards (sim not recorded)\"],[\"*\",\"gt3\",\"Imola\",103.364,null,\"GT3 leaderboard",
    "s (sim not recorded)\"],[\"*\",\"gt3\",\"Mugello\",107.222,null,\"GT3 leaderboards (sim not recorded)\"],[\"*\",\"gt3\",\"",
    "Nuerburgring\",115.416,null,\"GT3 leaderboards (sim not recorded)\"],[\"*\",\"gt3\",\"Hockenheim\",97.522,null,\"GT3 l",
    "eaderboards (sim not recorded)\"],[\"*\",\"gt3\",\"Oschersleben\",81.16,null,\"GT3 leaderboards (sim not recorded)\"]",
    ",[\"*\",\"gt3\",\"BrandsHatch\",82.152,null,\"GT3 leaderboards (sim not recorded)\"],[\"*\",\"gt3\",\"Sakhir\",118.476,nul",
    "l,\"GT3 leaderboards (sim not recorded)\"],[\"*\",\"gt3\",\"RoadAtlanta\",78.395,null,\"GT3 leaderboards (sim not rec",
    "orded)\"],[\"*\",\"gt3\",\"Nordschleife\",394.067,null,\"GT3 leaderboards (sim not recorded)\"],[\"*\",\"gt3\",\"Zhuhai\",9",
    "2.485,null,\"GT3 leaderboards (sim not recorded)\"],[\"*\",\"gt3\",\"Bathurst\",124.202,null,\"GT3 leaderboards (sim ",
    "not recorded)\"],[\"*\",\"gt3\",\"Fuji\",101.488,null,\"GT3 leaderboards (sim not recorded)\"],[\"*\",\"gt3\",\"DaytonaRoa",
    "d\",107.282,null,\"GT3 leaderboards (sim not recorded)\"],[\"*\",\"gt3\",\"SilverstoneNational\",52.62,null,\"GT3 lead",
    "erboards (sim not recorded)\"],[\"*\",\"gt3\",\"Jerez\",95.721,null,\"GT3 leaderboards (sim not recorded)\"]]}",
)))
_BENCH = None
_GRIP = {}
_BENCH_CLASSES = ("gt3", "gt4", "cup", "gte", "proto", "f1", "formula", "road")
_RE_PHRASE = re.compile(r"[a-z0-9]+( [a-z0-9]+)*")


def bench_problem(d):
    """None if d is a usable benchmark file, else what's wrong."""
    try:
        if not isinstance(d, dict) or not isinstance(d.get("tracks"), dict) or not isinstance(d.get("laps"), list):
            return "not a benchmark file"
        if len(d["laps"]) > 5000 or len(d["tracks"]) > 1000:
            return "too big"
        for k, o in d["tracks"].items():
            if not (re.fullmatch(r"[A-Za-z0-9]{2,40}", k) and isinstance(o, dict)
                    and isinstance(o.get("spoken"), str) and 2 <= len(o["spoken"]) <= 60 and o["spoken"].isprintable()
                    and isinstance(o.get("phrases"), list) and 1 <= len(o["phrases"]) <= 10
                    and all(isinstance(x, str) and _RE_PHRASE.fullmatch(x) for x in o["phrases"])
                    and type(o.get("length")) in (int, float) and 500 <= o["length"] <= 30000):
                return "bad track"
        for row in d["laps"]:
            if not (isinstance(row, list) and len(row) >= 5):
                return "bad lap row"
            sim, cls, tid, secs, car = row[:5]
            if not (isinstance(sim, str) and 1 <= len(sim) <= 30 and cls in _BENCH_CLASSES
                    and isinstance(tid, str) and re.fullmatch(r"[A-Za-z0-9]{2,40}", tid)
                    and type(secs) in (int, float) and 20 <= secs <= 1800
                    and (car is None or (isinstance(car, list) and 1 <= len(car) <= 10
                                         and all(isinstance(x, str) and _RE_PHRASE.fullmatch(x) for x in car)))):
                return "bad lap row"
    except Exception as e:
        return f"unreadable ({e})"
    return None


def benchmarks():
    global _BENCH
    if _BENCH is None:
        d = None
        try:
            with open(BENCH_PATH, encoding="utf-8") as fh:
                d = json.load(fh)
            if bench_problem(d):
                d = None
        except Exception:
            d = None
        _BENCH = d or STARTER_BENCH
    return _BENCH


def benchmarks_changed():
    global _BENCH
    _BENCH = None
    _GRIP.clear()


def benchmark_track(game, track, track_len):
    """The benchmark-only track (one without a starter lap) this sim track is: (id, spoken name), or None."""
    if game in RALLY_GAMES or not track_len:
        return None
    n = _plain_name(track)
    if " reverse " in n or " rev " in n:
        return None
    best = None
    for tid, o in benchmarks()["tracks"].items():
        if any(f" {ph} " in n for ph in o["phrases"]):
            off = abs(track_len - o["length"]) / o["length"]
            if off <= 0.03 and (best is None or off < best[0]):
                best = (off, tid, o["spoken"])
    return best[1:] if best else None


def benchmark_lap(game, car, cls, tid):
    """A quick lap time (s) for this sim, car class and track id: (seconds, True if it's for this very car), or
    None. This sim's own times come first, then times whose sim wasn't recorded; a time for the car itself beats
    one for its class. A RaceRoom car SimCoach can't put in a class gets none."""
    if not tid or (game == "RaceRoom" and raceroom_class(car) is None):
        return None
    n = _plain_name(car)
    best = None
    for row in benchmarks()["laps"]:
        sim, c, t_id, secs, phrases = row[:5]
        if t_id != tid or c != cls or sim not in (game, "*"):
            continue
        if phrases is not None and not any(f" {ph}" in n for ph in phrases):
            continue
        rank = (sim == game, phrases is not None)
        if best is None or rank > best[0]:
            best = (rank, float(secs), phrases is not None)
    return best[1:] if best else None


def starter_grip(tid, game, car, cls):
    """(grip factor, benchmark or None) for a starter lap at track tid: the factor makes the calculated lap for
    this class match the benchmark for this sim. Without a benchmark for the class, the GT3 correction for the
    track is used (it mostly corrects the track shape). A benchmark more than 10 % from the calculation, or one that
    needs a big grip change, is left alone: the car or the layout is too different from the model."""
    data = _starter_data()
    if tid not in data:
        return 1.0, None
    bench = benchmark_lap(game, car, cls, tid)
    use_cls, target = (cls, bench[0]) if bench else ("gt3", (benchmark_lap(game, "", "gt3", tid) or (None,))[0])
    if not target:
        return 1.0, bench
    key = (tid, use_cls, target)
    if key not in _GRIP:
        L, steps = data[tid]
        k, acc = [], 0
        for d in steps:
            acc += d
            k.append(acc / 1e5)

        def lap_t(gr):
            c = dict(STARTER_CARS.get(use_cls, STARTER_CARS["gt3"]))
            c["mu"], c["mu_brk"] = c["mu"] * gr, c["mu_brk"] * gr
            return _lap_sim(k, L / BINS, c)[4]
        g, base = 1.0, lap_t(1.0)
        if abs(target - base) / base <= 0.10:
            lo, hi = 0.6, 1.5
            for _ in range(15):
                g = (lo + hi) / 2
                if lap_t(g) > target:
                    lo = g
                else:
                    hi = g
            if not 0.85 <= g <= 1.2:                 # too big a correction: another layout, or an unusual car
                g = 1.0
        _GRIP[key] = g
    return _GRIP[key], bench


def starter_table():
    """Rows for the Starter laps table: every circuit with a starter lap (with the calculated lap time per car
    class) and every track that only has target times. Each row: (name, length m, kind, {class: seconds},
    targets text)."""
    def clock(x):
        return fmt_time(x).replace(" ", ":")
    b = benchmarks()
    short = {"gt3": "GT3", "gt4": "GT4", "cup": "Cup", "gte": "GTE", "proto": "Proto", "f1": "F1",
             "formula": "Formula", "road": "Road"}
    by_track = {}
    for row in b["laps"]:
        sim, cls, tid, secs, car = row[:5]
        what = car[0].title() if car else short.get(cls, cls)
        by_track.setdefault(tid, []).append(("Any sim" if sim == "*" else sim, what, float(secs)))

    def targets(tid):
        return "  ·  ".join(f"{sim} {what} {clock(secs)}" for sim, what, secs in
                            sorted(by_track.get(tid, []), key=lambda r: (r[0] == "Any sim", r[0], r[2])))
    rows = []
    data = _starter_data()
    for tid, (spoken, _phrases) in starter_tracks().items():
        times = {}
        for cls in ("gt3", "gt4", "proto", "f1"):
            st = starter_reference(tid, cls)
            if st:
                times[cls] = st["best_time"]
        rows.append((spoken[4:] if spoken.startswith("the ") else spoken, float(data[tid][0]),
                     "Built in" if tid in STARTER_TRACKS else "Library", times, targets(tid)))
    for tid, o in b["tracks"].items():
        if tid in by_track and tid not in data:      # a starter-lap track is listed above already
            name = o["spoken"]
            rows.append((name[4:] if name.startswith("the ") else name, float(o["length"]), "Target times only", {},
                         targets(tid)))
    rows.sort(key=lambda r: (r[2] == "Target times only", r[0].lower()))
    return rows


def track_file_problem(d):
    """None if d is a usable starter-lap track file from the library (references/tracks/), else what's wrong."""
    try:
        if not isinstance(d, dict):
            return "not a track file"
        tid = d.get("id")
        if not (isinstance(tid, str) and re.fullmatch(r"[A-Za-z0-9]{2,40}", tid)):
            return "bad id"
        if not (isinstance(d.get("spoken"), str) and 2 <= len(d["spoken"]) <= 60 and d["spoken"].isprintable()):
            return "bad spoken name"
        ph = d.get("phrases")
        if not (isinstance(ph, list) and 1 <= len(ph) <= 10
                and all(isinstance(x, str) and re.fullmatch(r"[a-z0-9]+( [a-z0-9]+)*", x) and 3 <= len(x) <= 40
                        for x in ph)):
            return "bad name phrases"
        L = d.get("length")
        if not (type(L) in (int, float) and 500 <= L <= 30000):
            return "bad length"
        steps = d.get("steps")
        if not (isinstance(steps, list) and len(steps) == BINS and all(type(x) is int for x in steps)):
            return "bad curvature data"
        acc = 0
        for x in steps:
            acc += x
            if abs(acc) > 20000:                     # 0.2 / m: tighter than a 5 m radius
                return "curvature out of range"
    except Exception as e:
        return f"unreadable ({e})"
    return None


def _starter_load():
    """Starter-lap tracks: the ones built into SimCoach plus any downloaded from the library (TRACK_DIR)."""
    global _STARTER_DATA, _STARTER_NAMES
    if _STARTER_DATA is None:
        try:
            import base64
            import zlib
            data = json.loads(zlib.decompress(base64.b64decode("".join(STARTER_TRACKS_B64))).decode())
        except Exception:
            data = {}
        names = {k: v for k, v in STARTER_TRACKS.items() if k in data}
        try:
            files = sorted(f for f in os.listdir(TRACK_DIR) if f.endswith(".json"))
        except OSError:
            files = []
        for f in files:
            try:
                with open(os.path.join(TRACK_DIR, f), encoding="utf-8") as fh:
                    d = json.load(fh)
                if track_file_problem(d) or d["id"] in data:
                    continue
                data[d["id"]] = [float(d["length"]), d["steps"]]
                names[d["id"]] = (d["spoken"], tuple(d["phrases"]))
            except Exception:
                continue
        _STARTER_DATA, _STARTER_NAMES = data, names
    return _STARTER_DATA, _STARTER_NAMES


def _starter_data():
    return _starter_load()[0]


def starter_tracks():
    """{track id: (spoken name, phrases matched against the sim's track name)} for every starter-lap track."""
    return _starter_load()[1]


def starter_tracks_changed():
    global _STARTER_DATA, _STARTER_NAMES
    _STARTER_DATA = _STARTER_NAMES = None
    _GRIP.clear()


def _plain_name(x):
    import unicodedata
    x = unicodedata.normalize("NFKD", str(x or "")).encode("ascii", "ignore").decode().lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", x).strip() + " "


def starter_track(game, track, track_len):
    """The starter-lap track for this sim track: its name must match and its length be within 3 % (so other
    layouts, e.g. Brands Hatch Indy or Silverstone National, are never used). None when there's no match."""
    if game in RALLY_GAMES or not track_len:
        return None
    n = _plain_name(track)
    if " reverse " in n or " rev " in n:
        return None
    data = _starter_data()
    for tid, (_spoken, phrases) in starter_tracks().items():
        if tid in data and any(f" {ph} " in n for ph in phrases):
            L = data[tid][0]
            if abs(track_len - L) / L <= 0.03:
                return tid
    return None


# RaceRoom's shared memory only gives a car's numeric model id. Names and classes: Sector3 Studios' r3e-data.json
# (github.com/sector3studios/r3e-spectator-overlay). Rebuild with tools/references/make_raceroom_cars.py.
RACEROOM_CARS_B64 = (
    "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"
)
_R3E = None
_R3E_CLASSES = (   # words in RaceRoom's class name -> SimCoach car class; first match wins
    ("formula", ("formula", "fr", "fr2", "fr3", "frj", "f4", "frx")),
    ("road", ("wtcr", "wtcc", "touring", "tcr", "nationals", "drift", "mx")),
    ("gt4", ("gtr 4", "gt4")),
    ("cup", ("cup", "carrera")),
    ("gte", ("gtr 2", "gte", "gt2", "gtr 1", "gto")),
    ("gt3", ("gtr 3", "gt masters", "gt3", "dtm 2021", "dtm 2023", "dtm 2024", "dtm 2025", "dtm 2026",
             "dtm esports 2022")),
    ("proto", ("p1", "p2", "hypercars", "group c", "dpi")),
)


def _raceroom():
    """({model id: (car name, SimCoach class or None)}, {car name: (model id, SimCoach class or None)}). A car
    that RaceRoom has in several classes gets the class in its name, so every name is one model id."""
    global _R3E
    if _R3E is None:
        try:
            import base64
            import zlib
            raw = json.loads(zlib.decompress(base64.b64decode("".join(RACEROOM_CARS_B64))).decode())
        except Exception:
            raw = {}
        seen = {}
        for name, _c in raw.values():
            seen[name] = seen.get(name, 0) + 1
        by_id, by_name = {}, {}
        for k, (name, cls_name) in raw.items():
            n = _plain_name(cls_name)
            cls = next((c for c, words in _R3E_CLASSES if any(f" {w} " in n for w in words)), None)
            if cls is None:                          # an unusual class: go by the car's own name, if it says
                cn = _plain_name(name)
                cls = next((c for c in ("gt4", "gte", "gt3") if f" {c} " in cn), None)
            shown = f"{name} ({cls_name})" if seen[name] > 1 and cls_name else name
            by_id[int(k)] = (shown, cls)
            by_name[shown] = (int(k), cls)
        _R3E = (by_id, by_name)
    return _R3E


def raceroom_car(model_id):
    """The car's name for a RaceRoom model id ('car 1738' when RaceRoom has added a car SimCoach doesn't know)."""
    hit = _raceroom()[0].get(int(model_id))
    return hit[0] if hit else f"car {int(model_id)}"


def raceroom_class(car):
    """The SimCoach car class of a RaceRoom car name, or None when it isn't known."""
    hit = _raceroom()[1].get(car)
    return hit[1] if hit else None


def car_class(game, car):
    if game == "F1 25":
        return "f1"
    if game == "RaceRoom":
        return raceroom_class(car) or "gt3"
    n = _plain_name(car)
    for cls, words in _STARTER_CLASS_WORDS:
        if any(f" {w}" in n for w in words):
            return cls
    return "gt3"


def _lap_sim(k, ds, car):
    """Quasi-steady lap simulation: corner speeds from grip + downforce, then accelerate (grip / power / drag) and
    brake (grip + downforce) into them with a friction ellipse. Returns speed m/s, throttle, brake, time."""
    g, rho = 9.81, 1.2
    m, P, mu, mub = car["m"], car["P"], car["mu"], car["mu_brk"]
    kd, kdrag = 0.5 * rho * car["ClA"] / m, 0.5 * rho * car["CdA"] / m
    n = len(k)
    ak = [abs(x) + 1e-9 for x in k]
    vlim = [min(120.0, math.sqrt(mu * g / (a - mu * kd)) if a > mu * kd else 120.0) for a in ak]

    def ellipse(v, i, mu_l):
        amax = mu * (g + kd * v * v)
        r = min(1.0, v * v * ak[i] / amax)
        return mu_l * (g + kd * v * v) * math.sqrt(max(0.0, 1.0 - r * r))
    start = min(range(n), key=vlim.__getitem__)
    order = [(start + j) % n for j in range(n)]
    v = [0.0] * n
    acc_lim = [False] * n
    v[start] = vlim[start]
    for a, b in zip(order, order[1:]):
        va = v[a]
        acc = min(ellipse(va, a, mu), P / (m * max(va, 5.0))) - kdrag * va * va
        vb = math.sqrt(max(va * va + 2 * acc * ds, 0.0))
        if vb >= vlim[b]:
            v[b] = vlim[b]
        else:
            v[b], acc_lim[b] = vb, True
    brk = [0.0] * n
    rev = order[::-1]
    for b, a in zip(rev, rev[1:]):
        vb = v[b]
        dec = ellipse(vb, b, mub) + kdrag * vb * vb
        va_max = math.sqrt(vb * vb + 2 * dec * ds)
        if va_max < v[a]:
            v[a], brk[a] = va_max, 1.0
    thr = [0.0 if brk[i] else (1.0 if acc_lim[i] else 0.45) for i in range(n)]
    # brake pressure: firm at the start of each stop, easing off towards the apex (trail braking)
    i = 0
    while i < n:
        if brk[i]:
            j = i
            while j < n and brk[j]:
                j += 1
            peak = min(1.0, max(0.55, 0.55 + 0.45 * v[i] / 70.0))
            for q in range(i, j):
                prog = (q - i) / max(1, j - i)
                brk[q] = round(peak * (1.0 - 0.6 * prog * prog), 3)
            i = j
        else:
            i += 1
    t, acc_t = [], 0.0
    for x in v:
        t.append(acc_t)
        acc_t += ds / max(x, 1.0)
    return v, thr, brk, t, acc_t


def starter_reference(tid, cls="gt3", shift=0, grip=1.0):
    """A complete SimCoach reference for track tid and car class cls. shift moves the track (in bins) to line it
    up with the sim's start line."""
    data = _starter_data()
    if tid not in data:
        return None
    L, steps = data[tid]
    k, acc = [], 0
    for d in steps:                                  # stored as differences, in 1e-5 / m
        acc += d
        k.append(acc / 1e5)
    if shift:
        shift %= BINS
        k = k[-shift:] + k[:-shift]
    car = dict(STARTER_CARS.get(cls, STARTER_CARS["gt3"]))
    # grip: from starter_grip(), tunes the lap to a real quick lap here when there's a benchmark
    car["mu"], car["mu_brk"] = car["mu"] * grip, car["mu_brk"] * grip
    v, thr, brk, t, lap_t = _lap_sim(k, L / BINS, car)
    ref = {"speed": [round(x * 3.6, 2) for x in v], "thr": thr, "brk": brk, "t": [round(x, 3) for x in t],
           "steer": [0.0] * BINS, "lock": [0] * BINS, "spin": [0] * BINS, "overlap": [0] * BINS}
    corners = find_corners(ref)
    return {"ref": ref, "best_time": round(lap_t, 3), "corners": corners,
            "best_corner": {ci: corner_metrics(ref, c) for ci, c in enumerate(corners)}}


_W0_PAD = int(0.015 * BINS)
_W1_PAD = int(0.006 * BINS)
_BP_PAD = int(0.01 * BINS)
_R0_PAD = int(0.005 * BINS)
_R1_PAD = int(0.004 * BINS)
_TRAIL_PAD = int(0.002 * BINS)


def corner_metrics(lap, c):
    s, apex, ex = c
    w0 = s - _W0_PAD if s > _W0_PAD else 0
    w1 = ex + _W1_PAD if ex + _W1_PAD < BINS - 1 else BINS - 1
    spd, brk, thr, t = lap["speed"], lap["brk"], lap["thr"], lap["t"]
    bp_end = w1 if w1 < apex + _BP_PAD else apex + _BP_PAD
    bp = None
    for k in range(w0, bp_end):
        if brk[k] > 0.15:
            bp = k
            break
    r0 = w0 if w0 > s - _R0_PAD else s - _R0_PAD
    r1 = (w1 if w1 < ex + _R1_PAD else ex + _R1_PAD) + 1
    spd_slice = spd[r0:r1]
    spd_reg = [x for x in spd_slice if x == x]
    min_spd = min(spd_reg) if spd_reg else 0.0
    mn = (r0 + spd_slice.index(min_spd)) if spd_reg else apex
    tp = w1
    for k in range(mn, w1 + 1):
        if thr[k] > 0.9:
            tp = k
            break
    coast = 0
    for k in range(r0, r1):
        if thr[k] < 0.05 and brk[k] < 0.05 and spd[k] > 40:
            coast += 1
    seg = t[w1] - t[w0]
    z0 = bp if bp is not None else s
    brk_reg = [x for x in brk[z0:mn + 1] if x == x] if z0 <= mn else ()
    peak = max(brk_reg) if brk_reg else 0.0
    tr_v = brk[max(s, mn - _TRAIL_PAD)] if bp is not None else 0.0
    trail = tr_v if tr_v == tr_v else 0.0
    flags = lap.get("lock")
    lock = spin = overlap = rev = 0
    if isinstance(flags, list) and len(flags) == BINS:
        lock = max(flags[w0:mn + 1]) if w0 <= mn else 0
    sp_arr = lap.get("spin")
    if isinstance(sp_arr, list) and len(sp_arr) == BINS:
        for k in range(mn, w1 + 1):
            if sp_arr[k]:
                spin = 1
                break
    ov_arr = lap.get("overlap")
    if isinstance(ov_arr, list) and len(ov_arr) == BINS:
        overlap = sum(ov_arr[r0:r1])
    st = lap.get("steer")
    if isinstance(st, list) and len(st) == BINS:
        prev = 0
        prev_st = st[mn - 1] if mn > 0 else st[mn]
        for k in range(mn, w1 + 1):
            cur_st = st[k]
            d = cur_st - prev_st
            prev_st = cur_st
            sgn = 1 if d > 0.01 else (-1 if d < -0.01 else 0)
            if sgn:
                if prev and sgn != prev:
                    rev += 1
                prev = sgn
    return {"bp": bp, "min_speed": min_spd, "tp": tp, "coast": coast, "seg": seg if seg >= 0 else math.nan,
            "peak_brake": peak, "trail": trail, "lock": lock, "spin": spin, "overlap": overlap, "corrections": rev}


def fmt_time(s):
    s = round(s, 1)
    m = int(s // 60)
    return f"{m} {s - 60 * m:04.1f}" if m else f"{s:.1f}"


_INF = (math.inf, -math.inf)


def _sane_frame(f, laps=0):
    """A frame with values that would break the maths: an unusable track position or clock drops it (None);
    other NaN / infinite numbers get safe values, positions just outside 0..1 are clamped. An unusable lap
    counter (some sims send -1 for a moment) becomes `laps`, the last good count, not 0: 0 reads as a restart."""
    p, ct = f.pct, f.cur_time
    if p is None or p != p or p in _INF or ct is None or ct != ct or ct in _INF:
        return None
    f.pct = 0.0 if p < 0.0 else (0.99999 if p >= 1.0 else p)
    for name in ("speed", "throttle", "brake", "steer", "fuel", "fuel_cap", "rpm", "max_rpm", "last_time"):
        v = getattr(f, name, 0.0)
        if v is None or v != v or v in _INF:
            setattr(f, name, 0.0)
    for name in ("laps_done", "position", "cars", "race_laps", "gear"):
        v = getattr(f, name, 0)
        if not (_sane_num(v) and (-10 <= v < 100000 if name == "gear" else 0 <= v < 100000)):
            setattr(f, name, laps if name == "laps_done" else 0)
        else:
            setattr(f, name, int(v))
    if f.time_left is not None and not 0.0 <= f.time_left < 1e7:
        f.time_left = None
    if f.track_len is not None and not 0.0 <= f.track_len < 1e6:
        f.track_len = None
    for name in ("gap_ahead", "gap_behind"):
        v = getattr(f, name, None)
        if v is not None and not 0.0 < v < 1e5:
            setattr(f, name, None)
    for name in ("water_temp", "oil_temp"):
        v = getattr(f, name, None)
        if v is not None and not 1.0 < v < 250.0:
            setattr(f, name, None)
    for name in ("energy", "energy_lap"):
        v = getattr(f, name, None)
        if v is not None and not 0.0 <= v <= 1.1:
            setattr(f, name, None)
    for name in ("rain", "damage", "rain_in_10", "rain_in_30", "rain_later", "precip"):
        v = getattr(f, name, None)
        if v is not None and not 0.0 <= v <= 10.0:
            setattr(f, name, None)
    if f.track_limits is not None:
        f.track_limits = int(f.track_limits) if (_sane_num(f.track_limits) and 0 <= f.track_limits < 10000) else None
    for name, n_el in (("tyre_temps", 4), ("tyre_press", 4), ("tyre_wear", 4), ("wheel_kmh", 4), ("damage_parts", 5)):
        lst = getattr(f, name, None)
        if lst is not None and not (isinstance(lst, (list, tuple)) and len(lst) == n_el and all(_sane_num(x) for x in lst)):
            setattr(f, name, None)
    if f.pos is not None and not (isinstance(f.pos, (list, tuple)) and len(f.pos) == 3 and all(_sane_num(x) for x in f.pos)):
        f.pos = None
    if f.right is not None and not (isinstance(f.right, (list, tuple)) and len(f.right) == 2 and all(_sane_num(x) for x in f.right)):
        f.right = None
    if f.others is not None:
        f.others = [o for o in f.others if isinstance(o, (list, tuple)) and len(o) == 3 and all(_sane_num(x) for x in o)]
    return f


def tenths(x):
    x = abs(x)
    if x >= 0.95:
        return f"{max(x, 1.0):.1f} seconds"
    n = round(x * 10)
    return "a tenth" if n <= 1 else f"{n} tenths"


def ok(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))




class Coach:
    def __init__(self, cfg, voice: Voice, overlay, store_dir, log=print):
        self.cfg, self.voice, self.overlay, self.store_dir, self.log = cfg, voice, overlay, store_dir, log
        self.lock = threading.RLock()
        self.capture = Capture(voice, log)
        self.key = None
        self.closed_after_finish = False
        self.straight_since = None
        self.reset_session()

    def reset_session(self):
        self.ref_source = None           # "own", "library" (the shared library) or "starter" (from the track shape)
        self._starter = None
        self._since_pit = 0
        self._rs = self._new_start_state()
        self.last_start = None
        self.drill = None
        self.drills_done = []
        self.ref = None
        self.best_time = None
        self.corners = []
        self.best_corner = {}
        self.history = []
        self.lap = Lap()
        self.last_laps_done = None
        self.spoken_exit, self.cued = set(), set()
        self.focus = []
        self.last_issue = {}
        self.track_len = None
        self.lap_no = 0
        self.last_frame: Optional[Frame] = None
        self.last_filled = None
        self.prev_i = None
        self.session_start = time.strftime("%Y-%m-%d %H:%M")
        self.session_id = f"{time.time():.3f}"
        self.last_report = None
        self.issue_counts = {}
        self.history_reported = 0
        self.beeped = {}
        self.frame_mono = 0.0
        self.crew = getattr(self, "crew", None)
        self.ref_segs = {}
        self.key_zones = []
        self.ref_provisional = False
        self._prev_pct = self._prev_cur = None
        self._bp_key, self._bp_list = None, ()
        self._head_sig = None
        self._exit_bins = {}
        self._all_cis = ()
        self._focus_cis = ()
        self._focus_cues = ()
        self._state_rev = 0
        self._post_t = 0.0
        if getattr(self, "_delta_shown", False):
            self.clear_delta()
        self._delta_shown = False
        self._last_head = None
        self.invalid_said = False
        self.session = None
        self.race_finished = False
        self.race_finished_at = None
        self.pit_debrief_done = False
        self._crossing_frames = []
        self._bc_prev_i = None
        self._lap_ahead = False
        self._session_report_path = None
        self._session_debrief_path = None
        self.pre_race_notes = {}
        self._last_tyre = None
        self.last_setup_briefing = None
        self.last_setup_sheet = None
        self.applied_setup = None
        self._sheet_wait = None
        self.last_debrief_txt = None

    _RE_SAFE_KEY = re.compile(r"[^A-Za-z0-9_.-]+")

    def _path(self):
        return os.path.join(self.store_dir, self._RE_SAFE_KEY.sub("_", "__".join(self.key)) + ".json")

    def _adopt_raceroom_legacy(self):
        """Before 6.10 RaceRoom cars were saved as 'car <model id>'. Move such a reference (and its session history)
        to the car's real name the first time it's needed."""
        if not self.key or self.key[0] != "RaceRoom" or os.path.exists(self._path()):
            return
        hit = _raceroom()[1].get(self.key[2])
        if not hit:
            return
        old = os.path.join(self.store_dir, self._RE_SAFE_KEY.sub("_", "__".join((self.key[0], self.key[1], f"car {hit[0]}"))) + ".json")
        try:
            with open(old, encoding="utf-8") as fh:
                d = json.load(fh)
            d["key"] = list(self.key)
            with open(self._path() + ".tmp", "w", encoding="utf-8") as fh:
                json.dump(d, fh, separators=(",", ":"))
            os.replace(self._path() + ".tmp", self._path())
            os.remove(old)
            olds = old.replace(".json", ".sessions.json")
            if os.path.exists(olds) and not os.path.exists(self._sessions_path()):
                os.replace(olds, self._sessions_path())
            self.log(f"RaceRoom reference moved to the car's name: {self.key[2]}")
        except FileNotFoundError:
            pass
        except Exception as e:
            self.log(f"Couldn't move the old RaceRoom reference: {e}")

    def load(self):
        try:
            self._adopt_raceroom_legacy()
            with open(self._path(), encoding="utf-8") as fh:
                d = json.load(fh)
            prob = ref_problem(d, need_key=False)
            if prob:
                self.log(f"Saved reference ignored: {prob}.")
                return False
            corners = [tuple(c) for c in d["corners"]]
            best_corner = {int(k): v for k, v in d["best_corner"].items()}
            old = (self.ref, self.best_time, self.corners, self.best_corner, self.ref_provisional)
            self.ref, self.best_time, self.corners, self.best_corner = d["ref"], d["best_time"], corners, best_corner
            self.ref_provisional = bool(d.get("provisional", False))
            self.ref_source = "library" if d.get("source") == "library" else "own"
            self._starter = None
            try:
                self._ref_changed()
            except Exception:
                self.ref, self.best_time, self.corners, self.best_corner, self.ref_provisional = old
                try:
                    self._ref_changed()
                except Exception:
                    pass
                raise
            return True
        except Exception:
            return False

    _SAVE_LOCK = threading.Lock()
    _SAVE_N = 0
    _SAVED = {}

    def save(self):
        """Write the reference in the background (it's ~100 KB of JSON; the telemetry loop must not stall).
        Starter laps are never saved: they're rebuilt from the track shape and replaced by the driver's own lap."""
        if self.ref_source == "starter" or self.ref is None:
            return
        data = {"key": list(self.key), "ref": self.ref, "best_time": self.best_time, "corners": list(self.corners),
                "best_corner": dict(self.best_corner), "saved": time.strftime("%Y-%m-%d %H:%M"),
                "provisional": bool(self.ref_provisional), "source": self.ref_source or "own"}
        path, store = os.path.abspath(self._path()), self.store_dir
        gen = self._ref_gen
        Coach._SAVE_N += 1
        seq = Coach._SAVE_N

        def write():
            tmp = path + ".tmp"
            try:
                with Coach._SAVE_LOCK:
                    if gen != self._ref_gen or seq < Coach._SAVED.get(path, 0):
                        return
                    Coach._SAVED[path] = seq
                    os.makedirs(store, exist_ok=True)
                    ref = data["ref"]
                    if ref and _np is not None:
                        data["ref"] = {k: (_np.round(_np.asarray(v, dtype=float), 3).tolist()
                                           if k in ("speed", "thr", "brk", "t", "steer") else v) for k, v in ref.items()}
                    text = json.dumps(data, separators=(",", ":"))
                    try:
                        with open(tmp, "w", encoding="utf-8") as fh:
                            fh.write(text)
                        os.replace(tmp, path)
                    except Exception:
                        try:
                            if os.path.exists(tmp):
                                os.remove(tmp)
                        except Exception:
                            pass
                        raise
            except Exception as e:
                self.log(f"Couldn't save the reference: {e}")
        threading.Thread(target=write, daemon=True, name="save-ref").start()

    def _ref_changed(self):
        self.ref_segs = {ci: corner_metrics(self.ref, c)["seg"] for ci, c in enumerate(self.corners)} if self.ref else {}
        self.key_zones = self._big_stops(3)
        self._all_cis = tuple(range(len(self.corners)))
        eb = {}
        win = int(0.01 * BINS)
        for ci, c in enumerate(self.corners):
            s, _apex, ex_c = c
            w0 = max(0, s - _W0_PAD)
            ex = min(BINS - 1, ex_c + _W1_PAD)
            item = (ci, c, w0, ex)
            for b_idx in range(ex, min(BINS, ex + win)):
                eb.setdefault(b_idx, []).append(item)
        self._exit_bins = eb
        self._state_rev += 1

    def _big_stops(self, n):
        """The n corners with the biggest speed drop on the reference: where most lap time usually is.
        Used for braking tones and first cues before there are laps to compare."""
        if not self.ref:
            return []
        spd, w = self.ref["speed"], int(0.01 * BINS)
        drops = []
        for ci, (s, apex, _ex) in enumerate(self.corners):
            if self.best_corner.get(ci, {}).get("bp") is None:
                continue
            drops.append((max(spd[max(0, s - w):apex + 1]) - spd[apex], ci))
        return [ci for d, ci in sorted(drops, reverse=True)[:n] if d > 20]

    def starter_focus(self):
        """Focus corners from one lap, so coaching starts on the very next lap: clear technique problems
        first (lock-ups, wheelspin, pedal overlap, coasting, sawing at the wheel), then the biggest stops."""
        found = []
        for ci in range(len(self.corners)):
            m = self.best_corner.get(ci) or {}
            opts = []
            if m.get("lock"):
                opts.append((40, "Build brake pressure smoothly, don't stab it."))
            if m.get("spin"):
                opts.append((30, "Unwind the wheel as you squeeze the throttle."))
            if m.get("overlap", 0) > 4:
                opts.append((15, "Clean pedal separation, off brake before throttle."))
            if m.get("coast", 0) and self.metres(m["coast"]) >= 25:
                opts.append((self.metres(m["coast"]) * 0.5, "Blend brake release straight to throttle, zero coasting."))
            if m.get("corrections", 0) >= 6:
                opts.append((8, "Light hands on exit, let the car breathe."))
            if opts:
                score, tip = max(opts)
                found.append((score, ci, tip))
        focus = [(ci, tip) for _, ci, tip in sorted(found, reverse=True)[:2]]
        tip = ("Brake on the last beep, then trail in to rotate the nose." if self.cfg.get("brake_callouts", "focus") != "off"
               else "Hit your braking marker, then trail in to rotate the nose.")
        for ci in self.key_zones:
            if len(focus) >= 2:
                break
            if ci not in dict(focus):
                focus.append((ci, tip))
        return focus

    def _set_focus(self, focus):
        self.focus = focus
        self._focus_cis = tuple(ci for ci, _ in focus)
        cues = []
        for ci, tip in focus:
            txt = self.cue_text(ci, tip)
            self.voice.prefetch(txt)
            if ci < len(self.corners):
                bp = self.best_corner.get(ci, {}).get("bp")
                c_start = min(self.corners[ci][0], bp) if bp is not None else self.corners[ci][0]
                cues.append((ci, c_start, txt, Voice.duration(txt) + 0.6))
        self._focus_cues = tuple(cues)
        self._state_rev += 1
        d = getattr(self, "drill", None)
        if d and focus and focus[0][0] == d["ci"]:
            self.overlay.post(focus=f"Drill  ·  {self.turn(d['ci'])}  ·  lap {d['done'] + 1} of {d['laps']}  ·  {focus[0][1]}")
            return
        self.overlay.post(focus="Focus  ·  " + "   ·   ".join(f"{self.turn(ci)}: {t}" for ci, t in focus)
                          if focus else "Focus  ·  consistency")

    # --- practice drills: one corner, a set number of laps, before/after comparison ---------------------------
    def _corner_losses(self, ci, ref_seg, n=3):
        """This corner's time lost against `ref_seg` on the last n clean laps (newest last)."""
        out = []
        for h in self.history:
            m = (h.get("corners") or {}).get(ci)
            if h.get("pit") or h.get("invalid") or not m or not ok(m.get("seg")):
                continue
            out.append(m["seg"] - ref_seg)
        return out[-n:]

    def start_drill(self, ci, laps=5):
        """Start a drill on corner index ci. Returns what to say."""
        with self.lock:
            f = self.last_frame
            if (f is not None and f.session == "race") or self.session == "race":
                return "Drills are for practice. Let's do one after the race."
            if not self.corners or not self.best_corner:
                return "Give me a clean lap first so I can map the corners, then ask again."
            if not 0 <= ci < len(self.corners):
                return f"I've only mapped {len(self.corners)} corners here. Pick turn 1 to {len(self.corners)}."
            laps = max(1, min(20, int(laps)))
            best = self.best_corner.get(ci) or {}
            ref = best.get("seg")
            if not ok(ref):
                return f"I haven't got clean data through {self.turn(ci)} yet. Do another lap first."
            base = self._corner_losses(ci, ref)
            last = next(((h.get("corners") or {}).get(ci) for h in reversed(self.history)
                         if (h.get("corners") or {}).get(ci) and not h.get("pit")), None)
            tip = (self.diagnose(last, best, cue=True) if last else None) or \
                "One thing at a time: hit your marker and carry speed to the apex."
            self.drill = {"ci": ci, "laps": laps, "done": 0, "ref_seg": ref, "tip": tip, "results": [],
                          "base": (sum(base) / len(base)) if base else None}
            self._set_focus([(ci, tip)])
            self._state_rev += 1
            return f"Drill on. {self.turn(ci)} for the next {_say_laps(laps)}, I'll only talk about that corner. {tip}"

    def stop_drill(self):
        with self.lock:
            if not self.drill:
                return "There's no drill running."
            msg = self._end_drill()
            self._set_focus(self.focus)
            return msg

    def _end_drill(self):
        """Close the drill, record it for the report and return the spoken wrap-up."""
        d, self.drill = self.drill, None
        turn, res = self.turn(d["ci"]), d["results"]
        if not res:
            return f"Drill on {turn} stopped before a clean lap through it."
        avg, best = sum(res) / len(res), min(res)
        self.drills_done.append({"turn": d["ci"] + 1, "laps": len(res), "planned": d["laps"], "before": d["base"],
                                 "avg": avg, "best": best})
        self._state_rev += 1
        out = [f"Drill done, {turn}, {_say_laps(len(res))}."]
        if d["base"] is not None:
            diff = d["base"] - avg
            if diff > 0.03:
                out.append(f"You averaged {tenths(diff)} better through there than before the drill.")
            elif diff < -0.03:
                out.append(f"You averaged {tenths(-diff)} slower there than before, so keep working on it.")
            else:
                out.append("About the same average as before the drill.")
        if best < -0.02:
            out.append(f"Best effort beat your old best through there by {tenths(best)}.")
        elif best < 0.03:
            out.append("Best effort matched your best through there.")
        else:
            out.append(f"Best effort was {tenths(best)} off your best there.")
        return " ".join(out)

    def adopt_reference(self):
        """A new saved reference for the current sim/track/car (an import): load it and rebuild everything that is
        keyed to its corner map (focus cues, issue counts, this session's per-corner lap data)."""
        with self.lock:
            if not self.load():
                return False
            self.issue_counts.clear()
            self.last_issue.clear()
            self.cued.clear()
            self.spoken_exit.clear()
            self.beeped.clear()
            for h in self.history:
                h["corners"] = {}
                h.pop("_filled", None)
            self._set_focus(self.starter_focus())
            self._state_rev += 1
            return True

    _ref_gen = 0

    def clear_reference(self, key=None, delete_file=False):
        """Forget the reference for the current (or given) track/car combo without erasing session lap history.
        delete_file: also remove the saved reference, so a restart doesn't bring it back (the spoken
        "reset reference"; the References tab deletes its files itself)."""
        with self.lock:
            if key is not None and tuple(key) != self.key:
                return
            with Coach._SAVE_LOCK:
                self._ref_gen += 1
                if self.key is not None:
                    Coach._SAVE_N += 1
                    Coach._SAVED[os.path.abspath(self._path())] = Coach._SAVE_N
                if delete_file and self.key is not None:
                    try:
                        os.remove(self._path())
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        self.log(f"Couldn't delete the saved reference: {e}")
            self.ref, self.best_time = None, None
            self.ref_provisional = False
            self.ref_source, self._starter = None, None
            for h in self.history:
                h["corners"] = {}
                h.pop("_filled", None)
                h.pop("provisional", None)
            self.last_filled = None
            self.corners, self.best_corner, self.focus = [], {}, []
            self.ref_segs, self.last_issue, self.issue_counts, self.key_zones = {}, {}, {}, []
            self._exit_bins, self._all_cis, self._focus_cis, self._focus_cues = {}, (), (), ()
            self._state_rev += 1

    def delete_saved_reference(self, key, paths):
        """References tab: delete a saved reference (and its progress file). If it's the combo being driven,
        the reference is forgotten first, so a save that's already under way can't write it back."""
        with self.lock:
            if key is not None and self.key is not None and tuple(key) == self.key:
                self.clear_reference(key)
            with Coach._SAVE_LOCK:
                Coach._SAVE_N += 1
                for p_ in paths:
                    Coach._SAVED[os.path.abspath(p_)] = Coach._SAVE_N
                    try:
                        os.remove(p_)
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        self.log(f"Couldn't delete {os.path.basename(p_)}: {e}")

    def import_reference(self, data, dest):
        """References tab: write an imported reference atomically; a save of the old reference that's still
        pending can't overwrite it. Adopted straight away if it's the combo being driven."""
        prob = ref_problem(data)
        if prob:
            raise ValueError(prob)
        key = tuple(data["key"])
        with self.lock:
            with Coach._SAVE_LOCK:
                if key == self.key:
                    self._ref_gen += 1
                Coach._SAVE_N += 1
                Coach._SAVED[os.path.abspath(dest)] = Coach._SAVE_N
                os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
                tmp = dest + ".tmp"
                try:
                    with open(tmp, "w", encoding="utf-8") as fh:
                        json.dump(data, fh)
                    os.replace(tmp, dest)
                except Exception:
                    try:
                        if os.path.exists(tmp):
                            os.remove(tmp)
                    except Exception:
                        pass
                    raise
            if key == self.key:
                return self.adopt_reference()
        return False

    def _keep_filled(self, n=8):
        """Lap traces are kept only while the reference is provisional (to re-score them once a clean lap
        replaces it), and only for the last n laps: each is ~0.5 MB, and a run of invalid laps can be long."""
        k = 0
        for h in reversed(self.history):
            if h.get("_filled"):
                k += 1
                if k > n:
                    h["_filled"] = False
                    h.pop("_seen", None)

    def _sessions_path(self):
        return self._path().replace(".json", ".sessions.json")

    def past_sessions(self):
        try:
            with open(self._sessions_path(), encoding="utf-8") as fh:
                d = json.load(fh)
            return [x for x in d if isinstance(x, dict)] if isinstance(d, list) else []
        except Exception:
            return []

    def _session_entry(self, best_t, times, ref_t, clean):
        """One row of the progress history: best lap, laps, and how the session went against the target."""
        cons = consistency_of(clean)
        pace = self.pace_pct(best_t) if clean else None
        t = self.target()
        return {"date": self.session_start, "best": best_t, "laps": len(times), "theoretical": self.theoretical_best(),
                "consistency": stdev(ref_t), "consistency_pct": round(cons["pct"], 3) if cons else None,
                "pace_pct": round(pace, 2) if pace else None, "target": t[0] if t else None}

    def snapshot_report(self):
        """Write a Coach Report for the laps so far without closing the session (no duplicate progress rows)."""
        with self.lock:
            if self.key is None or not self.history:
                return None
            times = [h["time"] for h in self.history]
            clean = [h["time"] for h in self.history if not h.get("pit") and not h.get("invalid")]
            ref_t = clean or [h["time"] for h in self.history if not h.get("pit")] or times
            best_t = min(ref_t)
            sess = self.past_sessions() + [self._session_entry(best_t, times, ref_t, clean)]
            try:
                path = write_report(self, sess, existing_path=self._session_report_path)
            except OSError as e:
                self.log(f"Couldn't write the coach report: {e}")
                return None
            self._session_report_path = path
            self.last_report = path
            return path

    def end_session(self):
        """Save progress and write the Coach Report. Safe to call more than once as new laps arrive."""
        with self.lock:
            if self.key is None or not self.history or len(self.history) == self.history_reported:
                return getattr(self, "last_report", None)
            times = [h["time"] for h in self.history]
            clean = [h["time"] for h in self.history if not h.get("pit") and not h.get("invalid")]
            ref_t = clean or [h["time"] for h in self.history if not h.get("pit")] or times
            best_t = min(ref_t)
            sess = self.past_sessions()
            entry = self._session_entry(best_t, times, ref_t, clean)
            entry["id"] = self.session_id
            if sess and sess[-1].get("id", sess[-1].get("date")) == self.session_id:
                sess[-1] = entry
            else:
                sess.append(entry)
            try:
                os.makedirs(self.store_dir, exist_ok=True)
                sp = self._sessions_path()
                stmp = sp + ".tmp"
                try:
                    with open(stmp, "w", encoding="utf-8") as fh:
                        json.dump(sess[-50:], fh)
                    os.replace(stmp, sp)
                except Exception:
                    if os.path.exists(stmp):
                        try:
                            os.remove(stmp)
                        except Exception:
                            pass
                    raise
                path = write_report(self, sess, existing_path=self._session_report_path)
            except OSError as e:
                self.log(f"Couldn't write the coach report: {e}")
                return getattr(self, "last_report", None)
            self._session_report_path = path
            self.history_reported = len(self.history)
            self.last_report = path
            self.log(f"Coach report: {path}")
            return path

    def metres(self, bins):
        return int(round(abs(bins) * (self.track_len or 4000.0) / BINS / 5.0) * 5) or 5

    @staticmethod
    def turn(i):
        return f"Turn {i + 1}"

    def say(self, text, now, kind="info", force=False):
        level = self.cfg.get("talk_level", 1)
        if level == 0 and kind in ("info", "cue"):
            return False
        if force or kind in ("answer", "urgent") or self.voice.idle(now):
            self.voice.say(text, now, kind)
            if kind != "cue":
                self.overlay.post(tip=text)
            return True
        return False

    # --- race starts: a reminder on the grid, then a launch + turn one review --------------------------------
    @staticmethod
    def _new_start_state():
        return {"phase": "idle", "still_t": None, "grid_pos": None, "t0": None, "last_t": None, "thr_min": 1.0,
                "spin": 0.0, "t100": None, "bog": False}

    def _race_start(self, f, now):
        """Standing starts only (a rolling start never sits still on the grid, so it's never armed)."""
        rs = getattr(self, "_rs", None)
        if rs is None:
            rs = self._rs = self._new_start_state()
        if f.session != "race" or f.game in RALLY_GAMES:
            if rs["phase"] != "idle":
                self._rs = self._new_start_state()
            return
        restart_edge = bool(f.restart) and not rs.get("restart_seen")
        if restart_edge:
            rs = self._rs = self._new_start_state()
        rs["restart_seen"] = bool(f.restart)
        ph = rs["phase"]
        if ph == "done":
            return
        if ph in ("idle", "grid"):
            if f.laps_done > 0:
                rs["phase"] = "done"
                return
            if f.speed < 3 and not f.in_pit:
                if rs["still_t"] is None:
                    rs["still_t"] = now
                if ph == "idle" and now - rs["still_t"] >= 2.0:
                    rs["phase"] = "grid"
                if rs["phase"] == "grid":
                    rs["grid_pos"] = f.position or rs["grid_pos"]
                    if not rs.get("told") and self.say(
                            "On the grid. Revs up, eyes on the lights, then smooth on the throttle as it hooks up. "
                            "Be sensible into turn one.", now):
                        rs["told"] = True
            elif ph == "grid" and f.speed >= 3:
                rs.update(phase="launch", t0=now, last_t=now)
            else:
                rs["still_t"] = None
            return
        # launch: measure the getaway until the end of turn one
        dt, step = now - rs["t0"], max(0.0, now - rs["last_t"])
        rs["last_t"] = now
        if 0.3 <= dt <= 1.5:
            rs["thr_min"] = min(rs["thr_min"], f.throttle)
        if dt <= 4.0 and f.wheel_kmh and f.speed > 5 and max(f.wheel_kmh) > f.speed * 1.15 + 3:
            rs["spin"] += step
        if rs["t100"] is None and f.speed >= 100 and dt <= 15:
            rs["t100"] = dt
        if 3.0 <= dt <= 3.5 and f.speed < 30:
            rs["bog"] = True
        if self.corners:
            reached = f.pct < 0.9 and f.pct * BINS >= _corner_window(self.corners[0])[1]
        else:
            reached = dt >= 25 or 0.25 < f.pct < 0.9
        if dt > 90:
            rs["phase"] = "done"
            return
        if not reached or dt < 5.0:        # never review before the launch has properly happened
            return
        rs["phase"] = "done"
        if rs["bog"]:
            launch = "You bogged down off the line, more revs when the lights go."
        elif rs["spin"] > 0.4:
            launch = "Too much wheelspin off the line, feed the throttle in over the first second."
        elif rs["thr_min"] < 0.7:
            launch = "You came off the throttle in the launch, commit once it hooks up."
        else:
            launch = "Clean launch."
        bits = [launch]
        if rs["t100"]:
            bits.append(f"Zero to a hundred in {rs['t100']:.1f} seconds.")
        g, p = rs["grid_pos"], f.position
        if g and p:
            d = g - p
            bits.append(f"P{p} after turn one, " + (f"up {d}." if d > 0 else f"down {-d}." if d < 0 else "held your place."))
        self.last_start = {"grid": g, "after_t1": p, "launch": launch, "zero_to_100_s": rs["t100"],
                           "wheelspin_s": round(rs["spin"], 2)}
        self.say("Start review. " + " ".join(bits), now, force=True)

    def _note_lap_context(self, f, now):
        """Things that cost time but aren't the driver's fault: traffic and yellow flags (per lap, and right now)."""
        prev, self._ctx_t = getattr(self, "_ctx_t", None), now
        dt = 0.0 if prev is None else max(0.0, min(0.5, now - prev))
        ca = f.car_ahead if isinstance(f.car_ahead, dict) else {}
        dist = ca.get("distance_m")
        close = f.speed > 30 and (bool(f.others) or (dist is not None and dist < 30)
                                  or (f.session == "race" and f.gap_ahead is not None and f.gap_ahead < 0.8))
        yellow = f.flag in ("yellow", "fcy", "sc", "vsc")
        self._traffic_now, self._yellow_now = close, yellow
        if yellow:
            self.lap.ctx_yellow = True
        if close:
            self.lap.ctx_traffic_s += dt

    # --- starter laps and the shared library -----------------------------------------------------------------------
    _CLASS_SPOKEN = {"gt3": "GT3 car", "gt4": "GT4 car", "cup": "cup car", "gte": "GTE car", "proto": "prototype",
                     "f1": "Formula 1 car", "formula": "single-seater", "road": "road car"}

    def _install_ref(self, d, provisional, source):
        self.ref, self.best_time = d["ref"], d["best_time"]
        self.corners = [tuple(c) for c in d["corners"]]
        self.best_corner = {int(k): v for k, v in d["best_corner"].items()}
        self.ref_provisional, self.ref_source = provisional, source
        self._ref_changed()

    def _target_line(self, bench, cls, where):
        """' A quick GT3 lap here is about 2 16.4.' for a benchmark (seconds, for this very car), else ''."""
        if not bench:
            return ""
        what = "lap in this car" if bench[1] else f"{self._CLASS_SPOKEN.get(cls, 'GT3 car').replace(' car', '')} lap"
        return f" A quick {what} {where} is about {fmt_time(bench[0])}."

    def _try_starter(self, f, now, name):
        """No lap of the driver's here: an approximate reference from the track shape, if it's a known track."""
        if not self.cfg.get("starter_laps", True):
            return False
        tid = starter_track(f.game, f.track, f.track_len)
        if tid is None:
            return False
        cls = car_class(f.game, f.car)
        grip, bench = starter_grip(tid, f.game, f.car, cls)
        st = starter_reference(tid, cls, grip=grip)
        if not st or len(st["corners"]) < 3:
            return False
        self._install_ref(st, True, "starter")
        self._starter = {"tid": tid, "cls": cls, "aligned": False, "grip": grip}
        self._set_focus(self.starter_focus())
        spoken = starter_tracks()[tid][0]
        target = self._target_line(bench, cls, "here")
        self.say(f"Radio check, {name}. No lap of yours here yet, so I've built a starter lap for {spoken} from the "
                 f"track layout, set up for a {self._CLASS_SPOKEN.get(cls, 'GT3 car')}.{target} Braking points are "
                 f"approximate. I'll line it up over the first part of the lap, then call them. Your first lap "
                 f"replaces it.", now, force=True)
        return True

    _ALIGN_W = 0.08        # how far (fraction of a lap) the sim's start line may sit from the starter lap's
    _ALIGN_AT = (0.25, 0.40, 0.55)     # tried when this much of the first lap has been driven

    def _starter_align(self, i, now):
        """Line the starter lap up with the sim's track: slide it along the lap until its speed trace has the same
        shape as the driver's so far (where they slow down and speed up depends on the track, not on their pace)."""
        st = self._starter
        if st is None or st["aligned"]:
            return
        tries = st.setdefault("tries", 0)
        if tries >= len(self._ALIGN_AT) or i < int(self._ALIGN_AT[tries] * BINS):
            return
        st["tries"] = tries + 1
        last = st["tries"] >= len(self._ALIGN_AT)
        spd = self.lap.speed
        lo = int(0.02 * BINS)                      # skip the launch / pit exit
        pts = [(b, spd[b]) for b in range(lo, min(i, BINS)) if spd[b] == spd[b]]
        best_s, best_c = 0, -1.0
        if len(pts) >= 0.6 * (i - lo):
            ref = self.ref["speed"]
            n = len(pts)
            my = sum(v for _b, v in pts) / n
            dy = [v - my for _b, v in pts]
            syy = sum(x * x for x in dy)
            W = int(self._ALIGN_W * BINS)
            if syy > n * 25.0:                     # the driver's speed really varied (not a slow cruise)
                for sft in range(-W, W + 1, 2):
                    xs = [ref[(b - sft) % BINS] for b, _v in pts]
                    mx = sum(xs) / n
                    sxy = sxx = 0.0
                    for x, y in zip(xs, dy):
                        x -= mx
                        sxy += x * y
                        sxx += x * x
                    c = sxy / math.sqrt(sxx * syy) if sxx > 0 else -1.0
                    if c > best_c:
                        best_s, best_c = sft, c
        if best_c < 0.8:
            if last:
                # the speed trace never fits: a different layout or version of the track
                self.clear_reference()
                self.ref_source, self._starter = None, None
                self.say("This track doesn't match my starter lap, so I'll map the corners from your first clean lap.",
                         now, force=True)
            return
        if abs(best_s) > 3:
            moved = starter_reference(st["tid"], st["cls"], shift=best_s, grip=st.get("grip", 1.0))
            if moved and len(moved["corners"]) >= 3:
                self._install_ref(moved, True, "starter")
                self._set_focus(self.starter_focus())
        st["aligned"], st["shift"] = True, best_s
        self.say("Starter lap lined up. Braking calls are on.", now, force=True)

    def _library_lookup(self, key, now):
        """Ask the shared SimCoach library for a reference for this exact sim, track and car (in the background)."""
        if not self.cfg.get("shared_refs", True) or key[0] == "TEST":
            return

        def work():
            try:
                d = fetch_library_lap(key)
            except Exception as e:
                file_log(f"Reference library: {type(e).__name__}: {e}")
                return
            if not d:
                return
            with self.lock:
                if self.key != tuple(key) or self.ref_source in ("own", "library"):
                    return
                dest = self._path()
            d["source"] = "library"
            try:
                if not self.import_reference(d, dest):
                    return
            except Exception as e:
                file_log(f"Reference library lap not used: {e}")
                return
            self.say(f"There's a reference lap for this car and track in the SimCoach library, {fmt_time(self.best_time)}. "
                     f"I'll coach you against it.", time.monotonic(), force=True)
        threading.Thread(target=work, daemon=True, name="ref-library").start()

    def target(self):
        """The benchmark lap for this sim, track and car: (seconds, True if it's for this very car, class), or
        None when there isn't one."""
        key, tl = self.key, self.track_len
        if not key:
            return None
        sig = (key, tl, id(benchmarks()), len(starter_tracks()))
        if getattr(self, "_target_sig", None) != sig:
            hit = None
            try:
                game, track, car = key
                tid = starter_track(game, track, tl)
                if tid is None:
                    bt = benchmark_track(game, track, tl)
                    tid = bt[0] if bt else None
                cls = car_class(game, car)
                b = benchmark_lap(game, car, cls, tid) if tid else None
                hit = (b[0], b[1], cls) if b else None
            except Exception:
                hit = None
            self._target_sig, self._target = sig, hit
        return self._target

    def pace_pct(self, lap_time):
        """A lap time as a percentage of the target lap (100 = on it), or None without a target."""
        t = self.target()
        return 100.0 * lap_time / t[0] if t and lap_time else None

    def target_words(self):
        t = self.target()
        if not t:
            return ""
        return "a quick lap in this car" if t[1] else f"a quick {self._CLASS_SPOKEN.get(t[2], 'GT3 car').replace(' car', '')} lap"

    def session_clean_times(self):
        return [h["time"] for h in self.history if not h.get("pit") and not h.get("invalid")]

    def theoretical_best(self):
        """Your best lap with every corner replaced by your best-ever run through that corner."""
        if not self.ref or self.best_time is None:
            return None
        saving = 0.0
        for ci, seg in self.ref_segs.items():
            b = self.best_corner.get(ci)
            if b and ok(seg) and ok(b.get("seg")):
                saving += max(0.0, seg - b["seg"])
        return self.best_time - saving

    def cue_text(self, ci, tip):
        return f"{self.turn(ci)}, {tip[0].lower()}{tip[1:]}"

    def update(self, f: Frame, now: float):
        p, tl, L = f.pct, f.time_left, f.track_len
        tt, tp, tw, wk, dp = f.tyre_temps, f.tyre_press, f.tyre_wear, f.wheel_kmh, f.damage_parts
        ga, gb, rn, dm, pos = f.gap_ahead, f.gap_behind, f.rain, f.damage, f.pos
        wt, ot, en, el, tlim = f.water_temp, f.oil_temp, f.energy, f.energy_lap, f.track_limits
        r10, r30, rl, pr, rt = f.rain_in_10, f.rain_in_30, f.rain_later, f.precip, f.right
        try:
            bad = (not 0.0 <= p < 1.0 or not -1e6 < f.cur_time < 1e6 or not -1e6 < f.last_time < 1e6
                   or not -1e4 < f.speed < 1e4 or not -10.0 < f.throttle < 10.0 or not -10.0 < f.brake < 10.0
                   or not -1e4 < f.steer < 1e4 or not -1e6 < f.fuel < 1e6 or not -1e6 < f.fuel_cap < 1e6
                   or not -1e6 < f.rpm < 1e7 or not 0.0 <= f.max_rpm < 1e7 or not 0 <= f.laps_done < 100000
                   or not 0 <= f.position < 100000 or not 0 <= f.cars < 100000 or not 0 <= f.race_laps < 100000
                   or not -10 <= f.gear < 100000 or (tlim is not None and not 0 <= tlim < 10000)
                   or (tl is not None and not 0.0 <= tl < 1e7) or (L is not None and not 0.0 <= L < 1e6)
                   or (ga is not None and not 0.0 < ga < 1e5) or (gb is not None and not 0.0 < gb < 1e5)
                   or (wt is not None and not 1.0 < wt < 250.0) or (ot is not None and not 1.0 < ot < 250.0)
                   or (en is not None and not 0.0 <= en <= 1.1) or (el is not None and not 0.0 <= el <= 1.1)
                   or (rn is not None and not 0.0 <= rn <= 10.0) or (dm is not None and not 0.0 <= dm <= 10.0)
                   or (r10 is not None and not 0.0 <= r10 <= 10.0) or (r30 is not None and not 0.0 <= r30 <= 10.0)
                   or (rl is not None and not 0.0 <= rl <= 10.0) or (pr is not None and not 0.0 <= pr <= 10.0)
                   or (tt is not None and (len(tt) != 4 or not -1e5 < sum(tt) < 1e5))
                   or (tp is not None and (len(tp) != 4 or not -1e5 < sum(tp) < 1e5))
                   or (tw is not None and (len(tw) != 4 or not -1e5 < sum(tw) < 1e5))
                   or (wk is not None and (len(wk) != 4 or not -1e5 < sum(wk) < 1e5))
                   or (dp is not None and (len(dp) != 5 or not -1e5 < sum(dp) < 1e5))
                   or (pos is not None and (len(pos) != 3 or not -1e8 < sum(pos) < 1e8))
                   or (rt is not None and (len(rt) != 2 or not -1e5 < sum(rt) < 1e5)))
        except TypeError:
            bad = True
        if bad:
            ll = self.last_laps_done
            ll = 0 if ll is None or f.session != self.session else (ll - 1 if self._lap_ahead else ll)
            f = _sane_frame(f, max(0, ll))
            if f is None:
                return
        with self.lock:
            self._update(f, now)

    def _start_new_session(self, f):
        self._rs = self._new_start_state()
        self.end_session()
        self.history = []
        self.issue_counts.clear()
        self.last_issue.clear()
        self.lap_no = 0
        self.history_reported = 0
        self._session_report_path = None
        self._session_debrief_path = None
        self.session_start = time.strftime("%Y-%m-%d %H:%M")
        self.session_id = f"{time.time():.3f}"
        self.last_report = None
        self.last_debrief_txt = None
        self.race_finished = False
        self.race_finished_at = None
        self.pit_debrief_done = False
        self._state_rev += 1
        self.lap = Lap()
        self._crossing_frames.clear()
        self.spoken_exit.clear()
        self.cued.clear()
        self.beeped.clear()
        self.prev_i = None
        self._prev_pct = self._prev_cur = None
        self.last_laps_done = f.laps_done
        self._lap_ahead = False

    def clear_delta(self):
        self._delta_shown = False
        self._last_delta_post = None
        self.overlay.post(delta="--.--", delta_color=C["fg"])

    def live(self):
        """True while a sim is sending telemetry (on track or in the pits)."""
        return time.monotonic() - self.frame_mono < 3.0

    def _update(self, f, now):
        if self.closed_after_finish and not f.race_over:
            self.closed_after_finish = False
            self.key = None
            if self.crew is not None:
                self.crew.key = None
        self.frame_mono = time.monotonic()
        self.last_frame = f
        try:
            self._race_start(f, now)
        except Exception as e:
            file_log(f"Race start coaching: {type(e).__name__}: {e}")
        self._note_lap_context(f, now)
        if self._sheet_wait is not None:
            sh = self.last_setup_sheet
            racing = (f.session == "race" or f.game in RALLY_GAMES) and (f.laps_done >= 1 or (f.speed > 50 and not f.in_pit))
            if (f.race_over or racing or time.monotonic() - self._sheet_wait > 900 or not sh
                    or sh.get("key") != ((f.game, f.track, f.car), self.session_id)):
                self._sheet_wait = None
            elif f.speed < 2 and f.in_pit:
                self._sheet_wait = None
                self.overlay.post(setup_sheet=sh, setup_popup=True)
        key = (f.game, f.track, f.car)
        if key != self.key:
            if self.key is not None:
                self.end_session()
            self.key = key
            self.reset_session()
            self.frame_mono = time.monotonic()
            self.last_frame = f
            self.track_len = f.track_len
            name = self.cfg.get("driver_name") or "driver"
            if self.load():
                past = self.past_sessions()
                extra = f" Last session you did {fmt_time(past[-1]['best'])}." if past else ""
                self._set_focus(self.starter_focus())
                self.say(f"Radio check, {name}. {f.track}, your best here is {fmt_time(self.best_time)}.{extra} "
                         f"{len(self.corners)} corners mapped, coaching is live.", now, force=True)
            elif not self._try_starter(f, now, name):
                target = ""
                bt = benchmark_track(f.game, f.track, f.track_len) if self.cfg.get("starter_laps", True) else None
                if bt:
                    cls = car_class(f.game, f.car)
                    target = self._target_line(benchmark_lap(f.game, f.car, cls, bt[0]), cls, f"at {bt[1]}")
                self.say(f"Radio check, {name}.{target} Give me a clean lap and I'll map the corners.", now, force=True)
            if self.ref_source in (None, "starter"):
                self._library_lookup(key, now)
        self.track_len = f.track_len or self.track_len
        if f.session != self.session:
            if self.session in ("practice", "qualifying") and f.session == "race":
                locks_p = sum(1 for h in self.history for cm in h.get("corners", {}).values() if cm.get("lock"))
                rear_p = sum(1 for h in self.history for cm in h.get("corners", {}).values() if cm.get("lock") == 2)
                spins_p = sum(1 for h in self.history for cm in h.get("corners", {}).values() if cm.get("spin"))
                fuels_p = [h.get("fuel", 0) for h in self.history if not h.get("pit") and h.get("fuel", 0) > 0.05]
                self.pre_race_notes = {
                    "from_session": self.session,
                    "laps": len(self.history),
                    "locks": locks_p,
                    "locks_rear": rear_p,
                    "spins": spins_p,
                    "fuel_per_lap": (sum(fuels_p) / len(fuels_p)) if fuels_p else None,
                    "issues": " ".join(k for d_ in self.issue_counts.values() for k in d_).lower(),
                }
                lt = self._last_tyre or (None, None, None, None)
                cur = (self.lap.max_temp, self.lap.min_temp, self.lap.max_press, self.lap.min_press)
                for k_, a_, b_ in zip(("max_temp", "min_temp", "max_press", "min_press"), lt, cur):
                    self.pre_race_notes[k_] = a_ if a_ is not None else b_
                self._start_new_session(f)
            elif self.race_finished and f.session != "race":
                self._start_new_session(f)
            elif self.session is not None:
                self.lap = Lap()
                self._crossing_frames.clear()
                self.spoken_exit.clear()
                self.cued.clear()
                self.beeped.clear()
                self.prev_i = None
                self._prev_pct = self._prev_cur = None
                self.last_laps_done = f.laps_done
                self._lap_ahead = False
            self.session = f.session

        straight = abs(f.steer) < 0.06 and f.brake < 0.05 and f.speed > 80
        if straight or self.race_finished:
            if self.straight_since is None:
                self.straight_since = now
            elif (self.race_finished or now - self.straight_since > 1.0) and not self.voice.on_straight.is_set():
                self.voice.on_straight.set()
        else:
            self.straight_since = None
            if self.voice.on_straight.is_set():
                self.voice.on_straight.clear()

        if self.last_laps_done is None:
            self.last_laps_done = f.laps_done

        crossed_line_pct = (self._prev_pct is not None and self._prev_pct > 0.88 and f.pct < 0.12)
        if crossed_line_pct and f.laps_done == self.last_laps_done and self.lap._samples < 180 and f.cur_time < 20.0:
            self.lap = Lap()
            self._crossing_frames.clear()
            self.prev_i = None

        restart = f.restart
        if (not restart and self.last_laps_done == f.laps_done and self._prev_pct is not None
                and abs(f.pct - self._prev_pct) > 0.2 and f.cur_time < self._prev_cur - 2.0
                and not (self._prev_pct > 0.88 and f.pct < 0.12) and not self._crossing_frames):
            restart = True
        self._prev_pct, self._prev_cur = f.pct, f.cur_time
        if restart:
            self.lap = Lap()
            self._crossing_frames.clear()
            self.spoken_exit.clear()
            self.cued.clear()
            self.beeped.clear()
            self.prev_i = None
        if self._lap_ahead and f.laps_done >= self.last_laps_done - 1:
            if f.laps_done >= self.last_laps_done:
                self._lap_ahead = False
            behind_by_one = (f.laps_done == self.last_laps_done - 1
                             and not (self.race_finished and not f.race_over and f.laps_done == 0))
        else:
            behind_by_one = False
        flushed = False
        restarted_finished = (self.race_finished and f.session == "race" and f.laps_done == 0
                              and not f.race_over and (f.time_left is None or f.time_left > 0.0))
        if (f.laps_done < self.last_laps_done and not behind_by_one) or restarted_finished:
            if self.race_finished or (self.history and f.session == "race" and f.laps_done == 0
                                      and self.last_laps_done >= 1):
                self._start_new_session(f)
            else:
                self.race_finished = False
                self.pit_debrief_done = False
                self.lap = Lap()
                self._crossing_frames.clear()
                self.spoken_exit.clear()
                self.cued.clear()
                self.beeped.clear()
                self.prev_i = None
                self.last_laps_done = f.laps_done
                self._lap_ahead = False
        elif f.laps_done > self.last_laps_done:
            if not self.race_finished:
                self.finish_lap(f.last_time, now)
            self.lap = Lap()
            for cf in self._crossing_frames:
                self.lap.add(cf)
            self._crossing_frames.clear()
            self.spoken_exit.clear()
            self.cued.clear()
            self.beeped.clear()
            self.prev_i = None
            self.last_laps_done = f.laps_done
        elif not self.race_finished and (crossed_line_pct or self._crossing_frames) and self.lap.coverage() > 0.70:
            if self._crossing_frames and f.pct >= 0.5:
                self._crossing_frames.clear()
            else:
                self._crossing_frames.append(f)
                if (not f.race_over and len(self._crossing_frames) >= 8
                        and max(cf.speed for cf in self._crossing_frames) < 15.0):
                    self.lap = Lap()
                    self._crossing_frames.clear()
                    self.spoken_exit.clear()
                    self.cued.clear()
                    self.beeped.clear()
                    self.prev_i = None
                elif f.race_over or (len(self._crossing_frames) >= 8 and (f.cur_time < 10.0 or len(self._crossing_frames) >= 15)):
                    if f.race_over or f.cur_time < 10.0 or (self.lap._t_hi > 10.0 and f.cur_time < self.lap._t_hi - 5.0):
                        self.finish_lap(f.last_time, now)
                        self.last_laps_done = f.laps_done + 1
                        self._lap_ahead = True
                    self.lap = Lap()
                    for cf in self._crossing_frames:
                        self.lap.add(cf)
                    self._crossing_frames.clear()
                    self.spoken_exit.clear()
                    self.cued.clear()
                    self.beeped.clear()
                    self.prev_i = None
                    flushed = True

        is_race_over = bool(
            f.race_over
            or (f.session == "race" and f.race_laps > 0 and f.laps_done >= f.race_laps)
            or (f.session == "race" and f.time_left is not None and f.time_left <= 0.0
                and self.lap_no > 0 and f.pct < 0.15 and self.lap._samples < 30)
        )
        if is_race_over and not self.race_finished:
            if self.lap.coverage() > 0.70 and self.lap._samples >= 30:
                self.finish_lap(f.last_time, now)
                self.lap = Lap()
                self._crossing_frames.clear()
            self._on_race_finished(f, now)

        if not self._crossing_frames and not self.race_finished and not flushed:
            self.lap.add(f)
            if self.lap.rewound:
                self.lap.rewound = False
                self.cued.clear()
                self.spoken_exit.clear()
                self.beeped.clear()

        if self.race_finished and not self.pit_debrief_done:
            parked_post_race = (
                self.race_finished_at is not None
                and now - self.race_finished_at >= 3.0
                and f.speed < 5.0
            )
            if f.in_pit or parked_post_race:
                self.pit_debrief_done = True
                self.after_race_debrief(f, now)

        i = min(BINS - 1, int(f.pct * BINS))
        starter = self.ref_source == "starter"
        delta = (f.cur_time - self.ref["t"][i] if self.ref is not None and f.cur_time > 1 and not self.race_finished
                 and not starter else None)
        if delta is not None and delta != delta:
            delta = None
        if now - self._post_t >= 0.1:
            self._post_t = now
            if delta is not None:
                d_str = f"{delta:+.2f}"
                d_col = "#ef5350" if delta > 0 else "#66bb6a"
                if getattr(self, "_last_delta_post", None) != (d_str, d_col):
                    self._last_delta_post = (d_str, d_col)
                    self.overlay.post(delta=d_str, delta_color=d_col)
                self._delta_shown = True
            elif self._delta_shown:
                self.clear_delta()
            sig = (f.game, f.track, f.car, self.best_time, f.session, f.position, f.cars, self.race_finished)
            if sig == self._head_sig:
                head = self._last_head
            else:
                self._head_sig = sig
                head = f"{f.game} · {f.track} · {f.car}" + (" · starter lap" if self.ref_source == "starter" else
                                                             f" · best {fmt_time(self.best_time)}" if self.best_time else "")
                if f.session == "race" and f.position:
                    head += f" · {'Finished' if self.race_finished else 'Race'} P{f.position}" + (f"/{f.cars}" if f.cars else "")
                elif self.race_finished:
                    head += " · Race finished"
            if head != self._last_head:
                self._last_head = head
                self.overlay.post(head=head)
        if not self.race_finished:
            if delta is not None and self.prev_i is not None and not f.in_pit and \
                    (self.cfg.get("split_callouts") or self.cfg.get("talk_level", 1) >= 2):
                for mark in (BINS // 3, 2 * BINS // 3):
                    if self.prev_i < mark <= i:
                        self.say("Matching your best." if abs(delta) < 0.05 else
                                 f"{'Up' if delta < 0 else 'Down'} {tenths(delta)}.", now)
            if self.corners and not f.in_pit:
                if starter:
                    self._starter_align(i, now)
                    if self._starter is not None and self._starter["aligned"]:
                        self.cue_focus(f, i, now)
                        self.brake_countdown(f, i)
                else:
                    self.cue_focus(f, i, now)
                    self.exit_feedback(i, now)
                    self.brake_countdown(f, i)
        self.prev_i = i
        if self.crew is not None:
            self.crew.update(f, now)

    def brake_countdown(self, f, i):
        """Three tones that land on your reference braking point: 1 s out, 0.5 s out, and BRAKE."""
        mode = self.cfg.get("brake_callouts", "focus")
        if mode == "off" or f.speed < 40:
            return
        key = (mode, self._state_rev)
        if key != self._bp_key:
            scope = self._all_cis if mode == "all" else (self._focus_cis or self.key_zones)
            bc = self.best_corner
            self._bp_key = key
            self._bp_list = tuple((ci, bc[ci]["bp"]) for ci in scope if bc.get(ci, {}).get("bp") is not None)
        if not self._bp_list:
            return
        bin_m_over_v = ((self.track_len or 4000.0) / BINS) / (f.speed / 3.6)
        prev = self._bc_prev_i
        self._bc_prev_i = i
        step = ((i - prev) % BINS) * bin_m_over_v if prev is not None else 0.0
        last = min(0.12, max(0.03, step))
        beeped = self.beeped
        for ci, bp in self._bp_list:
            t_to = ((bp - i) % BINS) * bin_m_over_v
            if t_to > 3.0:
                if beeped.get(ci, 0) > 0 and t_to > 4.0:
                    beeped[ci] = 0
                continue
            n = beeped.get(ci, 0)
            if n < 3 and t_to <= (1.0, 0.5, last)[n]:
                self.voice.tone(1250 if n == 2 else 760, 150 if n == 2 else 80)
                beeped[ci] = n + 1

    def cue_focus(self, f, i, now):
        if f.speed < 30 or not self._focus_cues:
            return
        bins_per_sec = (f.speed / 3.6) / ((self.track_len or 4000.0) / BINS)
        cued = self.cued
        for ci, c_start, text, base_need in self._focus_cues:
            if ci in cued:
                continue
            dist = (c_start - i) % BINS
            if dist == 0 or dist > bins_per_sec * (base_need + 0.9):
                continue
            need = base_need + self.voice.latency(text)
            if dist <= bins_per_sec * need:
                cued.add(ci)
                if dist > bins_per_sec * (need - 0.6):
                    self.say(text, now, kind="cue")

    def exit_feedback(self, i, now):
        candidates = self._exit_bins.get(i)
        if not candidates:
            return
        spoken = self.spoken_exit
        for ci, c, w0, w1 in candidates:
            if ci in spoken:
                continue
            spoken.add(ci)
            if self.drill and ci != self.drill["ci"]:
                continue
            if getattr(self, "_traffic_now", False) or getattr(self, "_yellow_now", False):
                continue                          # held up or under a yellow: not the driver's fault
            if self.lap.pit or ci not in self.best_corner or self.lap.has_off_in(w0, w1) or not self.lap.observed(w0, w1):
                continue
            filled = self.lap.filled_window(w0, w1)
            if filled is None:
                continue
            m, best = corner_metrics(filled, c), self.best_corner[ci]
            if not ok(m["seg"]) or not ok(best.get("seg")):
                continue
            loss = m["seg"] - best["seg"]
            if loss > LOSS_TO_MENTION:
                reason = self.diagnose(m, best)
                if reason:
                    self.last_issue[ci] = (loss, reason)
                    self.issue_counts.setdefault(ci, {})
                    cnt = self.issue_counts[ci].get(reason, 0) + 1
                    self.issue_counts[ci][reason] = cnt
                    self._state_rev += 1
                    minor = (self.cfg.get("talk_level", 1) < 2 and ci not in self._focus_cis and loss < 0.3
                             and not (self.drill and ci == self.drill["ci"]))
                    if not minor:                 # normal talk level: focus corners, or a big loss anywhere
                        spoken_reason = self._unhinged_flair(ci, m, best, reason, loss, cnt)
                        self.say(f"{self.turn(ci)}, {tenths(loss)} lost. {spoken_reason}", now)
            elif loss < -0.05 and (self.cfg.get("talk_level", 1) >= 2 or ci in self._focus_cis):
                self.say(f"Mega through {self.turn(ci)}, fastest yet.", now)

    def _unhinged_flair(self, ci, m, best, reason, loss, cnt):
        """Inject a bit of unhinged coach energy on mistakes while keeping the technical diagnosis crystal clear."""
        style = self.cfg.get("coach_personality", DEFAULT_CONFIG["coach_personality"])
        if style in ("mansell", "bentley", "perel", "naujoks"):
            return reason
        if m.get("lock"):
            where = "fronts" if m["lock"] == 1 else "rears"
            return (f"You locked the {where} into square bricks! Stop stabbing the pedal like you're trying to kill a spider — "
                    f"build pressure smoothly.")
        if m.get("spin"):
            return "Wheelspin on exit! The throttle isn't a light switch — unwind the wheel before you feed the power."
        if m.get("overlap", 0) > 4:
            return "You're pressing brake and throttle at the same time — your feet are fighting each other! Clean pedal separation."
        if m.get("corrections", 0) >= 4 and m.get("corrections", 0) > best.get("corrections", 0) + 2:
            return "You're sawing at the wheel like a lumberjack on exit! Light hands, let the car breathe."
        if "released the brake too early" in reason:
            return "You dumped the brake at turn-in and threw away all your front rotation! Trail the brake to the apex."
        if "Initial brake pressure was too soft" in reason:
            return "Why are we tickling the brake pedal?! Attack peak pressure at the marker, then bleed it off."
        if "went in too deep" in reason:
            return "Hero entry, zero exit! You charged in way too deep and parked it at the apex."
        if "coasted" in reason:
            return "Stop coasting mid-corner like you're lost in a school zone! Blend brake release straight to throttle."
        if "braked" in reason and "early" in reason:
            if loss >= 0.35 or cnt >= 2:
                return f"{reason} My grandmother brakes deeper than that — trust your marker!"
            return f"{reason} Trust the grip and push the zone."
        if "Apex speed" in reason and (loss >= 0.30 or cnt >= 2):
            return f"{reason[:-1]} — you practically stopped for coffee at the apex!"
        if "Full throttle" in reason and (loss >= 0.25 or cnt >= 2):
            return f"{reason[:-1]} — what are we waiting for, a written invitation? Rotate and commit!"
        if cnt >= 3:
            return f"That's {cnt} times in {self.turn(ci)} now! {reason}"
        return reason

    def diagnose(self, m, best, cue=False):
        opts = []
        if m.get("lock"):
            where = "fronts" if m["lock"] == 1 else "rears"
            opts.append((40, "Build brake pressure smoothly, don't stab it." if cue else f"You locked the {where}. Ease off the initial brake pressure."))
        if m.get("spin"):
            opts.append((30, "Unwind the wheel as you squeeze the throttle." if cue else "Wheelspin on exit. Squeeze the throttle, don't snap it."))
        if m.get("overlap", 0) > 4:
            opts.append((15, "Clean pedal separation, off brake before throttle." if cue else "You overlapped brake and throttle there."))
        if (m["bp"] is not None and best.get("bp") is not None and best["bp"] - m["bp"] > 0
                and m.get("peak_brake", 1) < 0.75 * best.get("peak_brake", 1)):
            opts.append(((best["bp"] - m["bp"]) + 6, "Hit the brake harder at the start, then bleed it off." if cue
                         else "Initial brake pressure was too soft. Hit it harder, then bleed off."))
        b_vmin = best.get("min_speed", 0.0)
        m_vmin = m.get("min_speed", 0.0)
        if (best.get("trail", 0) > 0.15 and m.get("trail", 0) < 0.05 and b_vmin - m_vmin > 2):
            opts.append((12, "Trail the brake to the apex to rotate the nose." if cue else "You released the brake too early. Trail it in to rotate the car."))
        if m.get("corrections", 0) >= 4 and m.get("corrections", 0) > best.get("corrections", 0) + 2:
            opts.append((8, "Light hands on exit, let the car breathe." if cue else "Car was unsettled on exit. Smoother hands and throttle."))
        if m.get("bp") is not None and best.get("bp") is not None:
            early = best["bp"] - m["bp"]
            if early > 0 and self.metres(early) >= 10:
                opts.append((early + 2, f"Push the braking point {self.metres(early)} metres deeper." if cue
                             else f"You braked {self.metres(early)} metres early."))
            elif early < 0 and self.metres(early) >= 10 and m_vmin < b_vmin - 2:
                opts.append((-early * 0.8 + 2, f"Brake {self.metres(early)} metres earlier and prioritise the exit." if cue
                             else "You went in too deep and scrubbed speed."))
        dv = b_vmin - m_vmin
        if dv > 3:
            opts.append((dv * 1.5, f"Carry {int(round(dv))} more k p h to the apex." if cue
                         else f"Apex speed {int(round(dv))} k p h down. Come off the brake earlier."))
        if m.get("tp") is not None and best.get("tp") is not None:
            late = m["tp"] - best["tp"]
            if late > 0 and self.metres(late) >= 15:
                opts.append((late * 0.6, "Rotate early and get to full throttle sooner." if cue
                             else f"Full throttle {self.metres(late)} metres later than your best."))
        coast = m.get("coast", 0) - best.get("coast", 0)
        if coast > 0 and self.metres(coast) >= 15:
            opts.append((coast * 0.7, "Blend brake release straight to throttle, no coasting." if cue
                         else "You coasted there. Go brake to throttle sooner."))
        return max(opts, key=lambda o: o[0])[1] if opts else None

    def collaborate_race_setup(self, f: Optional[Frame], now: float, speak: bool = True,
                               use_openai: bool = True, user_query: str = "", show: bool = False,
                               session_start: bool = False) -> tuple[str, str]:
        """Before the race begins (or when requested), the Strategist and Coach work together to recommend
        an optimal setup for the race based on track geometry, weather/rain, race length, fuel, tyre temps/pressures,
        and the driver's telemetry tendencies. Uses the chosen AI provider when an API key is configured, with built-in fallback."""
        with self.lock:
            f = f or self.last_frame
            sim_name = (f.game if f else (self.key[0] if self.key else "Sim")) or "Sim"
            track_raw = (f.track if f else (self.key[1] if self.key else "")) or ""
            car_raw = (f.car if f else (self.key[2] if self.key else "")) or ""
            track = nice_name(track_raw) or "the circuit"
            car = nice_name(car_raw) or "car"
            rain = (f.rain if (f and f.rain is not None) else 0.0) or 0.0
            crew = self.crew

            est_lap_s = self.best_time or (crew.avg_lap() if crew else None)
            if not est_lap_s:
                past = self.past_sessions()
                est_lap_s = (past[-1].get("best") if past else None) or 90.0
            race_laps = f.race_laps if (f and f.race_laps) else (
                max(1, math.ceil(f.time_left / est_lap_s)) if (f and f.time_left) else 0
            )
            fpl_seen = (crew.fuel_per_lap() if crew else None) or self.pre_race_notes.get("fuel_per_lap")
            fpl = fpl_seen or 2.4
            max_p = self.pre_race_notes.get("max_press") or self.lap.max_press
            min_p = self.pre_race_notes.get("min_press") or self.lap.min_press
            max_t = self.pre_race_notes.get("max_temp") or self.lap.max_temp
            min_t = self.pre_race_notes.get("min_temp") or self.lap.min_temp
            items = []
            if rain >= 0.35:
                cond_txt = "wet track conditions"
                tyre_call = "bolt on full wet tyres and raise starting pressures 1.0 PSI to keep the grooves open"
                items += [("Tyres", "Compound", "Full wets"),
                          ("Tyres", "Starting pressures", "+1.0 psi (keeps the grooves open)")]
            elif rain >= 0.05:
                cond_txt = "damp crossover conditions"
                tyre_call = "start on slicks with pressures up 0.4 PSI for faster warm-up, or wets if heavy rain is imminent"
                items += [("Tyres", "Compound", "Slicks (wets if heavy rain is close)"),
                          ("Tyres", "Starting pressures", "+0.4 psi for a faster warm-up")]
            else:
                cond_txt = "dry conditions"
                if max_p and max_p > 28.5:
                    tyre_call = "run medium-slick compound and bleed starting pressures down 0.6 PSI so they stabilise around 27.3 PSI hot"
                    items += [("Tyres", "Compound", "Medium slick"),
                              ("Tyres", "Starting pressures", "-0.6 psi, to settle around 27.3 psi hot")]
                elif min_p and min_p < 25.8:
                    tyre_call = "bump cold tyre pressures up 0.5 PSI so you hit the 27.0 to 27.5 PSI grip window on lap two"
                    items += [("Tyres", "Starting pressures", "+0.5 psi, for 27.0 to 27.5 psi hot by lap two")]
                elif max_t and max_t > 102:
                    tyre_call = "open the brake ducts one click and drop rear cold pressures 0.4 PSI to control thermal degradation"
                    items += [("Brakes", "Brake ducts", "Open 1 click"),
                              ("Tyres", "Rear starting pressures", "-0.4 psi, to control the heat")]
                else:
                    tyre_call = "target 27.0 to 27.4 PSI hot on slicks with balanced brake ducts"
                    items += [("Tyres", "Hot pressures", "27.0 to 27.4 psi on slicks"),
                              ("Brakes", "Brake ducts", "Balanced")]

            grid_txt = f"starting P{f.position} of {f.cars}, " if (f and f.position and f.cars) else (f"starting P{f.position}, " if (f and f.position) else "")
            target_fuel = math.ceil((race_laps + 1.2) * fpl) if race_laps > 0 else None
            cap = f.fuel_cap if (f and f.fuel_cap and f.fuel_cap > 0) else 120.0
            stop_plan = "no-stop"
            g_ = f.game if f else None
            fuel_items = []
            if race_laps > 0 and target_fuel is not None:
                if f is not None and f.game in RALLY_GAMES:
                    fuel_call = f"{_say_laps(race_laps)} in {cond_txt}, {grid_txt}pack {min(int(cap), target_fuel)} {fuel_unit(f.game, min(int(cap), target_fuel))} for the stage"
                    fuel_items = [("Fuel", "Fuel load", f"{min(int(cap), target_fuel)} {fuel_unit(g_)} for the stage")]
                elif target_fuel > cap and f is not None and f.game in NO_REFUEL_GAMES:
                    fuel_call = (f"{_say_laps(race_laps)} in {cond_txt}, {grid_txt}fill it to {int(cap)} {fuel_unit(f.game, int(cap))}, "
                                 f"there's no refuelling, so plan to lift and coast")
                    fuel_items = [("Fuel", "Fuel load", f"Full, {int(cap)} {fuel_unit(g_)}"),
                                  ("Strategy", "Plan", "No refuelling: lift and coast to make the distance")]
                elif target_fuel > cap:
                    stint1 = int(cap)
                    n_stops = max(1, math.ceil(target_fuel / cap) - 1)
                    stop_plan = {1: "one-stop", 2: "two-stop", 3: "three-stop"}.get(n_stops, f"{n_stops}-stop")
                    fuel_call = f"{_say_laps(race_laps)} in {cond_txt}, {grid_txt}load {stint1} {fuel_unit(f.game if f else None, stint1)} for a {stop_plan} strategy"
                    fuel_items = [("Fuel", "Starting fuel", f"{stint1} {fuel_unit(g_)} (a full tank)"),
                                  ("Strategy", "Plan", f"{stop_plan.capitalize()}, about {target_fuel} {fuel_unit(g_)} for the race")]
                else:
                    fuel_call = f"{_say_laps(race_laps)} in {cond_txt}, {grid_txt}pack {target_fuel} {fuel_unit(f.game if f else None, target_fuel)} for a no-stop run"
                    fuel_items = [("Fuel", "Fuel load", f"{target_fuel} {fuel_unit(g_)}"),
                                  ("Strategy", "Plan", "No stop")]
            else:
                fuel_call = f"In {cond_txt}, {grid_txt}pack 1.5 laps of reserve fuel"
                fuel_items = [("Fuel", "Fuel load", "The race distance plus 1.5 laps of reserve")]
            fuel_items.append(("Fuel", "Use per lap", f"About {fpl:.1f} {fuel_unit(g_)}" +
                               ("" if fpl_seen else " (a guess until SimCoach has timed a lap)")))
            items = fuel_items + items

            strat_line = (
                f"Strategist {'pre-race ' if not (f and f.session in ('practice', 'qualifying')) else ''}"
                f"setup for {track}: {fuel_call}, and {tyre_call}. "
                f"Coach, what's the call on chassis and aero?"
            )

            tl_low = track_raw.lower()
            high_speed_kw = ("monza", "spa", "le mans", "sarthe", "daytona", "bathurst", "watkins", "paul ricard", "silverstone", "baku", "jeddah")
            tech_kw = ("monaco", "hungar", "zandvoort", "brands", "imola", "laguna", "barcelona", "catalunya", "suzuka", "nurburgring", "misano")
            avg_vmin = None
            if self.corners and self.best_corner:
                vmins = [self.best_corner[ci].get("min_speed", 0) for ci in range(len(self.corners)) if self.best_corner.get(ci)]
                if vmins:
                    avg_vmin = sum(vmins) / len(vmins)
            if rain >= 0.30:
                aero_call = "crank on two extra clicks of rear wing for wet braking and high-speed stability"
                items.append(("Aero", "Rear wing", "+2 clicks (wet braking and stability)"))
            elif any(k in tl_low for k in high_speed_kw) or (avg_vmin and avg_vmin > 125):
                aero_call = "trim the rear wing one to two clicks for straight-line top speed so you aren't a sitting duck in the slipstream"
                items.append(("Aero", "Rear wing", "-1 to -2 clicks (top speed)"))
            elif any(k in tl_low for k in tech_kw) or (avg_vmin and avg_vmin < 95):
                aero_call = "run medium-high downforce with +1 millimetre front rake to plant the nose through the technical sequences"
                items += [("Aero", "Downforce", "Medium-high"), ("Suspension", "Rake", "+1 mm")]
            else:
                aero_call = "run a balanced baseline wing with a touch of positive rake so the front bites on turn-in"
                items += [("Aero", "Rear wing", "Baseline"), ("Suspension", "Rake", "A touch more (positive rake)")]

            locks = self.pre_race_notes.get("locks", 0) + sum(
                1 for h in self.history for cm in h.get("corners", {}).values() if cm.get("lock")
            )
            locks_rear = self.pre_race_notes.get("locks_rear", 0) + sum(
                1 for h in self.history for cm in h.get("corners", {}).values() if cm.get("lock") == 2
            )
            spins = self.pre_race_notes.get("spins", 0) + sum(
                1 for h in self.history for cm in h.get("corners", {}).values() if cm.get("spin")
            )
            all_issues = (self.pre_race_notes.get("issues", "") + " "
                          + " ".join(k for d in self.issue_counts.values() for k in d.keys())).lower()
            unhinged = self.cfg.get("coach_personality", DEFAULT_CONFIG["coach_personality"]) in ("apex", "almeida")

            mech_bits = []
            if rain >= 0.25:
                mech_bits.append("shift brake bias 1.5 percent rearward, soften both anti-roll bars two clicks, and bump TC and ABS up two clicks for the wet")
                items += [("Brakes", "Brake bias", "1.5 % rearward"), ("Suspension", "Anti-roll bars", "Both 2 clicks softer"),
                          ("Electronics", "TC and ABS", "Both 2 clicks up (wet)")]
            else:
                rear_issue = all_issues.count("locked the rears")
                front_issue = all_issues.count("locked the fronts")
                if (locks > 0 or rear_issue or front_issue) and locks_rear + rear_issue > (locks - locks_rear) + front_issue:
                    mech_bits.append(
                        "shift brake bias 0.8 percent forward — the rears are locking and that's a spin waiting to happen"
                        if unhinged else "move brake bias 0.8 percent forward so the rears stop locking in the heavy stops"
                    )
                    items.append(("Brakes", "Brake bias", "0.8 % forward (the rears are locking)"))
                elif locks > 0 or "locked" in all_issues:
                    mech_bits.append(
                        "shift brake bias 0.8 percent rearward and set ABS up one click so you stop flat-spotting the fronts"
                        if unhinged else "move brake bias 0.8 percent rearward to prevent front lock-ups in the heavy stops"
                    )
                    items.append(("Brakes", "Brake bias", "0.8 % rearward (the fronts are locking)"))
                    if unhinged:
                        items.append(("Electronics", "ABS", "+1 click"))
                elif self.key_zones:
                    mech_bits.append("nudge brake bias 0.5 percent rearward to help the car trail-brake and rotate into the heavy stops")
                    items.append(("Brakes", "Brake bias", "0.5 % rearward (rotation on trail-braking)"))
                if spins > 0 or "wheelspin" in all_issues or "unsettled" in all_issues:
                    mech_bits.append(
                        "soften the rear anti-roll bar one click and drop diff preload so the rear hooks up when you get greedy on exit"
                        if unhinged else "soften the rear anti-roll bar one click and lower diff preload for cleaner exit traction"
                    )
                    items += [("Suspension", "Rear anti-roll bar", "1 click softer"),
                              ("Differential", "Preload", "Lower (cleaner exit traction)")]
                elif "apex speed" in all_issues or "released the brake too early" in all_issues:
                    mech_bits.append("soften the front anti-roll bar one click to kill mid-corner understeer and carry more minimum speed")
                    items.append(("Suspension", "Front anti-roll bar", "1 click softer (mid-corner understeer)"))
                else:
                    mech_bits.append("keep the front anti-roll bar one click softer than rear with progressive diff preload for smooth rotation to throttle")
                    items += [("Suspension", "Anti-roll bars", "Front 1 click softer than the rear"),
                              ("Differential", "Preload", "Progressive")]

            coach_line = (
                f"Copy Strategist. On the {car}, {aero_call}, and {', '.join(mech_bits)}. "
                f"Setup's dialled — trust the platform!"
            )

            setup_ctx = {
                "sim": sim_name,
                "fuel_unit": fuel_unit(f.game if f else None),
                "race_refuelling": not (f is not None and f.game in NO_REFUEL_GAMES),
                "track": track,
                "car": car,
                "track_length_m": self.track_len,
                "session": f.session if f else self.session,
                "weather_condition": cond_txt,
                "rain_intensity_0_to_1": round(rain, 2),
                "race_laps": race_laps,
                "time_left_s": round(f.time_left) if (f and f.time_left) else None,
                "grid_position": f.position if (f and f.position) else None,
                "field_size": f.cars if (f and f.cars) else None,
                "fuel_per_lap_l": round(fpl, 2),
                "target_race_fuel_l": target_fuel,
                "fuel_capacity_l": round(cap, 1),
                "stop_strategy": stop_plan,
                "tyre_temps_c": [round(x) for x in f.tyre_temps] if (f and f.tyre_temps) else None,
                "tyre_pressures_psi": [round(x, 1) for x in f.tyre_press] if (f and f.tyre_press) else None,
                "logged_max_temp_c": round(max_t, 1) if max_t else None,
                "logged_min_temp_c": round(min_t, 1) if min_t else None,
                "logged_max_press_psi": round(max_p, 1) if max_p else None,
                "logged_min_press_psi": round(min_p, 1) if min_p else None,
                "avg_corner_min_speed_kmh": round(avg_vmin, 1) if avg_vmin else None,
                "corners_mapped": len(self.corners),
                "heavy_braking_turns": [ci + 1 for ci in self.key_zones],
                "driver_locks_logged": locks,
                "driver_wheelspins_logged": spins,
                "driver_corner_issues": {f"Turn {ci + 1}": v for ci, v in self.issue_counts.items()},
                "baseline_strategist_call": strat_line,
                "baseline_coach_call": coach_line,
            }
            if user_query:
                setup_ctx["driver_question"] = user_query

            self.last_setup_briefing = {"strategist": strat_line, "coach": coach_line, "source": "built-in"}
            ses_lbl = f.session.capitalize() if (f and f.session in ("practice", "qualifying")) else None
            if ses_lbl:
                race_txt = ses_lbl + (f", {max(1, round(f.time_left / 60))} minutes" if f.time_left else "")
            elif race_laps > 0:
                race_txt = f"{'Stage' if (f and f.game in RALLY_GAMES) else 'Race'}, {_say_laps(race_laps)}"
            elif f and f.time_left:
                race_txt = f"Race, {max(1, round(f.time_left / 60))} minutes"
            else:
                race_txt = "Race"
            sheet = {"title": f"{track} · {car}", "sim": sim_name, "race": race_txt, "conditions": cond_txt.capitalize(),
                     "grid": f"Start P{f.position}" + (f" of {f.cars}" if f.cars else "") if (f and f.position) else "",
                     "items": items, "strategist": strat_line, "coach": coach_line, "source": "Built-in advisor",
                     "made": time.strftime("%d %b %H:%M"), "key": (self.key, self.session_id)}
            api_key = ai_key(self.cfg)
            is_test_sim = (sim_name == "TEST")

        # The session-start sheet: forced open (even on the move) before the first lap is done, unless the
        # driver switched the automatic pop-up off, in which case it's only kept for the overlay's SETUP button.
        autopop = bool(self.cfg.get("sheet_autopop", True))
        lf_s = f or self.last_frame
        if session_start and autopop and (lf_s is None or lf_s.laps_done == 0):
            show = True
        pop = "never" if (session_start and not autopop) else "auto"
        if use_openai and api_key and not (speak and is_test_sim):
            if speak:
                threading.Thread(
                    target=self._openai_setup_worker,
                    args=(api_key, setup_ctx, strat_line, coach_line, now, time.monotonic(),
                          (self.key, self.session_id), sheet, show, pop, session_start),
                    daemon=True,
                    name="openai-race-setup",
                ).start()
                return strat_line, coach_line
            s_ai, c_ai, src, ai_items = self._fetch_openai_setup(api_key, setup_ctx, strat_line, coach_line)
            with self.lock:
                self.last_setup_briefing = {"strategist": s_ai, "coach": c_ai, "source": src}
            self._publish_setup_sheet(self._ai_sheet(sheet, s_ai, c_ai, src, ai_items), force=show, popup=pop)
            return s_ai, c_ai

        if speak:
            self._speak_setup_pair(strat_line, coach_line, now, sheet, force=show, popup=pop, start=session_start)
        else:
            self._publish_setup_sheet(sheet, force=show, popup=pop)
        return strat_line, coach_line

    @staticmethod
    def _ai_sheet(sheet, s_line, c_line, src, ai_items):
        """The written sheet for a GPT briefing: GPT's own list when it gave one, else the steps of what it said
        (never the built-in list, which could disagree with what was said on the radio)."""
        out = dict(sheet, strategist=s_line, coach=c_line, source=src)
        if src.startswith("built-in") or (not ai_items and (s_line, c_line) == (sheet.get("strategist"), sheet.get("coach"))):
            return out
        out["items"] = ai_items or [("From the radio", "", step) for step in _radio_steps(f"{s_line} {c_line}")]
        out["applied"] = set()
        return out

    def _publish_setup_sheet(self, sheet, force=False, popup="auto"):
        """Keep the sheet, save it as text next to the reports, and show it (the app opens the pop-up).
        force: the driver asked to see it (button / "show the setup sheet"), so it opens even on the move."""
        if not sheet:
            return
        groups = OrderedDict()
        for it in sheet.get("items") or []:
            groups.setdefault(it[0], []).append(tuple(it))
        sheet["items"] = [it for rows in groups.values() for it in rows]
        sheet.setdefault("applied", set())
        sheet["coach_ref"] = self
        with self.lock:
            if sheet.get("key") is not None and sheet["key"] != (self.key, self.session_id):
                return
            self.last_setup_sheet = sheet
        try:
            with SetupApplier._IO_LOCK:
                os.makedirs(REPORT_DIR, exist_ok=True)
                stem = _RE_SAFE_REPORT.sub("_", f"{time.strftime('%Y-%m-%d_%H%M')}_{sheet.get('title', 'setup')}")
                path = os.path.join(REPORT_DIR, f"{stem}_setup.txt")
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(setup_sheet_text(sheet))
                os.replace(tmp, path)
                sheet["path"] = path
        except OSError as e:
            self.log(f"Couldn't save the setup sheet: {e}")
        if popup == "never":                 # automatic pop-up switched off: ready behind the SETUP button
            with self.lock:
                self._sheet_wait = None
            self.overlay.post(setup_sheet=sheet, setup_popup=False)
            return
        lf = self.last_frame
        moving = not force and lf is not None and self.live() and lf.speed > 3
        with self.lock:
            self._sheet_wait = time.monotonic() if moving else None
        if moving:
            self.log("Setup sheet ready. It opens when you stop in the pits, or say \"show the setup sheet\".")
        self.overlay.post(setup_sheet=sheet, setup_popup=not moving)

    def _speak_setup_pair(self, strat_line: str, coach_line: str, now: float, sheet=None, force=False, popup="auto",
                          start=False):
        crew = self.crew
        if crew and crew.on("strategist"):
            # The session-start briefing is a priority call: it goes ahead of intros and banter and never
            # expires from the queue, so it's always heard. Briefings asked for later queue as normal.
            crew.say("strategist", strat_line, now, urgent=start)
            crew.say("coach", coach_line, now, urgent=start)
        else:
            self.say(strat_line, now, force=True)
            self.say(coach_line, now, force=True)
        self.voice.last_text = f"{strat_line} {coach_line}"
        lf0 = self.last_frame
        self.overlay.post(tip=f"{'Setup' if (lf0 and lf0.session in ('practice', 'qualifying')) else 'Pre-Race Setup'} · {coach_line}")
        # The session-start sheet opens even on the move (it never takes focus from the game), as long as the
        # first lap hasn't been completed yet; one that arrives later waits for a stop as before.
        lf = self.last_frame
        self._publish_setup_sheet(sheet, force=bool(force and (lf is None or lf.laps_done == 0)), popup=popup)

    def _fetch_openai_setup(self, api_key: str, setup_ctx: dict,
                            fallback_strat: str, fallback_coach: str) -> tuple:
        """Ask the chosen AI for a race-specific Strategist + Coach setup briefing tailored to the car, track,
        weather, race length, and driver telemetry."""
        driver = self.cfg.get("driver_name") or "the driver"
        p_key = self.cfg.get("coach_personality", DEFAULT_CONFIG["coach_personality"])
        coach_persona = COACH_PERSONA_PROMPTS.get(p_key, COACH_PERSONA_PROMPTS["apex"]).format(name=driver)
        sys_msg = (
            f"You are coordinating a pre-race setup briefing over team radio for {driver} between two people:\n"
            f"1) STRATEGIST ({CREW_PERSONAS['strategist']}): covers race distance, starting grid slot, weather/surface, "
            f"exact starting fuel in {setup_ctx.get('fuel_unit', 'litres')} "
            f"({'and stop strategy' if setup_ctx.get('race_refuelling', True) else 'no refuelling in this sim, so no fuel stops'}), "
            f"tyre compound, and cold/hot tyre pressure & brake duct targets "
            f"for this specific sim, track, and car, then hands off to the Coach.\n"
            f"2) COACH ({coach_persona}): replies to the Strategist with specific mechanical, aero, and electronics setup "
            f"changes tailored to the exact car architecture (e.g. engine placement, drivetrain, aero sensitivity), the track's "
            f"corners/straights/kerbs, the weather, and {driver}'s logged telemetry issues (lock-ups, wheelspin, understeer/oversteer). "
            f"Include concrete adjustments (wing clicks, ride height/rake, front/rear ARB, diff preload, brake bias %, TC/ABS).\n\n"
            f"Format rules:\n"
            f"- Reply with ONLY a JSON object: {{\"strategist\": \"...\", \"coach\": \"...\", \"sheet\": [...]}}.\n"
            f"- strategist and coach: what each one says on the radio, 1 to 2 spoken sentences each (at most 36 words). "
            f"No lists, no markdown, no emojis. Say numbers naturally for speech (e.g. '27.2 PSI', '0.8 percent rearward').\n"
            f"- sheet: the written setup sheet {driver} follows in the garage: 4 to 12 objects "
            f"{{\"area\": one of Fuel, Strategy, Tyres, Brakes, Aero, Suspension, Differential, Electronics, Other, "
            f"\"setting\": the setup item (e.g. \"Rear wing\"), \"change\": the exact change or value (e.g. \"-1 click\", "
            f"\"62 litres\", \"0.8 % rearward\")}}. It must contain every change said on the radio, with the same numbers."
        )
        user_msg = f"RACE & TELEMETRY CONDITIONS: {json.dumps(setup_ctx, separators=(',', ':'))}"
        try:
            raw, who = ai_chat_ex(
                self.cfg,
                [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
                max_tokens=700,
            )
            s_out, c_out = parse_setup_dialogue(raw, fallback_strat, fallback_coach)
            if s_out == fallback_strat or c_out == fallback_coach:
                self.log(f"{who}'s setup reply was incomplete; using the built-in setup advisor.")
                return fallback_strat, fallback_coach, "built-in (fallback)", None
            return s_out, c_out, who, parse_setup_sheet(raw)
        except Exception as e:
            self.log(f"AI pre-race setup unavailable ({type(e).__name__}: {e}); using built-in setup advisor.")
            return fallback_strat, fallback_coach, "built-in (fallback)", None

    def _openai_setup_worker(self, api_key: str, setup_ctx: dict, fallback_strat: str, fallback_coach: str,
                             start_now: float, start_mono: float, sess=None, sheet=None, show=False, pop="auto",
                             start=False):
        s_out, c_out, src, ai_items = self._fetch_openai_setup(api_key, setup_ctx, fallback_strat, fallback_coach)
        with self.lock:
            if sess is not None and sess != (self.key, self.session_id):
                self.log("Setup briefing arrived after the session changed; not used.")
                return
            self.last_setup_briefing = {"strategist": s_out, "coach": c_out, "source": src}
        cur_now = start_now + max(0.0, time.monotonic() - start_mono)
        self._speak_setup_pair(s_out, c_out, cur_now, self._ai_sheet(sheet, s_out, c_out, src, ai_items) if sheet else None,
                               force=show, popup=pop, start=start)

    def finish_lap(self, lap_time, now):
        lap = self.lap
        self.lap_no += 1
        since_pit = getattr(self, "_since_pit", 0)
        self._since_pit = 0 if lap.pit else since_pit + 1
        if lap.max_temp is not None or lap.max_press is not None:
            self._last_tyre = (lap.max_temp, lap.min_temp, lap.max_press, lap.min_press)
        f = self.last_frame
        in_race = bool((f and f.session == "race") or self.session == "race")
        own = lap._t_hi
        if own > 10 and (lap_time <= 10 or abs(lap_time - own) > 3.0):
            lap_time = own
        wall_timed = False
        if lap_time <= 10:
            wt = lap.wall_time()
            if wt > 10:
                lap_time, wall_timed = wt, True
        if lap_time <= 10:
            return
        if lap.pit and not in_race:
            return
        cov = lap.coverage()
        filled = lap.filled() if cov >= 0.25 else None
        fuel_used = max(0.0, (lap.fuel_start or 0) - (lap.fuel_end or 0))
        if cov <= 0.80 or filled is None:
            if (in_race or self.ref is not None) and cov >= 0.25 and lap._samples >= 30 and not wall_timed:
                per = {ci: corner_metrics(filled, c) for ci, c in enumerate(self.corners)
                       if lap.observed(*_corner_window(c))} if (filled and self.corners) else {}
                self.history.append({"time": lap_time, "corners": per, "fuel": fuel_used,
                                     "invalid": bool(lap.invalid), "pit": bool(lap.pit), "partial": True,
                                     "_filled": filled if self.ref_provisional else None,
                                     "_seen": bytes(lap.seen) if (self.ref_provisional and filled) else None})
                self._keep_filled()
                if self.best_time is None and not lap.invalid and not lap.pit:
                    self.best_time = lap_time
                self._state_rev += 1
            elif self.ref is None and cov >= 0.15:
                self.say("Didn't see that whole lap. I'll map the corners on the next one.", now, force=True)
            return
        if lap.pit and in_race:
            per = {ci: corner_metrics(filled, c) for ci, c in enumerate(self.corners)} if self.corners else {}
            self.history.append({"time": lap_time, "corners": per, "fuel": fuel_used,
                                 "invalid": bool(lap.invalid), "pit": True,
                                 "_filled": filled if self.ref_provisional else None})
            self._keep_filled()
            self._state_rev += 1
            return
        if lap.invalid and self.ref is not None:
            self.last_filled = filled
            per = {ci: corner_metrics(filled, c) for ci, c in enumerate(self.corners)}
            self.history.append({"time": lap_time, "corners": per, "fuel": fuel_used,
                                 "invalid": True, "pit": False,
                                 "_filled": filled if self.ref_provisional else None})
            self._keep_filled()
            w = lambda c: (max(0, c[0] - _W0_PAD), min(BINS - 1, c[2] + _W1_PAD))
            corner_pb = False
            for ci, m in per.items():
                b = self.best_corner.get(ci)
                lo, hi = w(self.corners[ci])
                if b is not None and ok(m["seg"]) and not lap.has_off_in(lo, hi) and \
                        (not ok(b.get("seg")) or m["seg"] < b["seg"]):
                    self.best_corner[ci] = m
                    corner_pb = True
            focus_inv = []
            for ci in range(len(self.corners)):
                lo, hi = w(self.corners[ci])
                if not lap.has_off_in(lo, hi) and ok(per[ci]["seg"]) and ok(self.best_corner.get(ci, {}).get("seg")):
                    loss_c = per[ci]["seg"] - self.best_corner[ci]["seg"]
                    if loss_c > 0.08:
                        tip = self.diagnose(per[ci], self.best_corner[ci], cue=True)
                        if tip:
                            focus_inv.append((loss_c, ci, tip))
            if focus_inv:
                self._set_focus([(ci, tip) for _, ci, tip in sorted(focus_inv, reverse=True)[:2]])
            self._state_rev += 1
            if corner_pb:
                self.save()
            nxt = f" Next lap, {self.turn(self.focus[0][0])}: {self.focus[0][1]}" if self.focus else ""
            unhinged_inv = self.cfg.get("coach_personality", DEFAULT_CONFIG["coach_personality"]) in ("apex", "almeida")
            inv_msg = ("Lap invalid — we're circuit racing, not mowing the lawn! Keep it between the white lines."
                       if unhinged_inv else "Lap invalid, not counted for your best.") + nxt
            self.say(inv_msg, now, force=True)
            return
        if self.ref is None or self.ref_source == "starter" or (self.ref_provisional and not lap.invalid):
            replacing = self.ref is not None
            was_starter = self.ref_source == "starter"
            self.ref_source, self._starter = "own", None
            self.ref_provisional = bool(lap.invalid)
            self.last_filled = filled
            self.ref = filled
            self.best_time = lap_time
            self.corners = find_corners(filled)
            self.best_corner = {ci: corner_metrics(filled, c) for ci, c in enumerate(self.corners)}
            if replacing:
                self.issue_counts.clear()
                self.last_issue.clear()
                for h in self.history:
                    h.pop("provisional", None)
                    h_filled = h.pop("_filled", None)
                    seen = h.pop("_seen", None)
                    if h_filled:
                        h["corners"] = {ci: corner_metrics(h_filled, c) for ci, c in enumerate(self.corners)
                                        if seen is None or _observed(seen, *_corner_window(c))}
                    else:
                        h["corners"] = {}
            self.history.append({"time": lap_time, "corners": dict(self.best_corner), "provisional": self.ref_provisional,
                                 "fuel": fuel_used, "invalid": bool(lap.invalid), "pit": False,
                                 "_filled": filled if self.ref_provisional else None})
            self._keep_filled()
            self._ref_changed()
            self.save()
            self._set_focus(self.starter_focus())
            first = f" First up, {self.turn(self.focus[0][0])}: {self.focus[0][1]}" if self.focus else ""
            if was_starter:
                msg = (f"{fmt_time(lap_time)}. That's your own reference now, {len(self.corners)} corners, so I'll coach "
                       f"you against your own driving from here.{first}")
            elif replacing:
                msg = f"Clean lap, {fmt_time(lap_time)}. Finally kept it on the island — that's our proper reference now.{first}"
            elif self.ref_provisional:
                msg = (f"{fmt_time(lap_time)}. Messy excursion off track, but I've still mapped {len(self.corners)} corners from it. "
                       f"Live coaching starts now.{first}")
            else:
                msg = (f"Copy. {fmt_time(lap_time)}, baseline set. {len(self.corners)} corners mapped. "
                       f"Live coaching starts now.{first}")
            self.say(msg, now, force=True)
            return

        self.last_filled = filled
        per = {ci: corner_metrics(filled, c) for ci, c in enumerate(self.corners)}
        self.history.append({"time": lap_time, "corners": per, "fuel": fuel_used,
                             "invalid": False, "pit": False})
        improved = []
        changed = False
        for ci, m in per.items():
            b = self.best_corner.get(ci)
            if b is None or not ok(m["seg"]):
                continue
            if not ok(b.get("seg")) or m["seg"] < b["seg"]:
                if ok(b.get("seg")) and (b["seg"] - m["seg"]) >= 0.04:
                    improved.append((b["seg"] - m["seg"], ci))
                self.best_corner[ci] = m
                self._state_rev += 1
                changed = True
        pb = self.best_time is None or lap_time < self.best_time
        delta = (lap_time - self.best_time) if self.best_time is not None else 0.0
        if pb:
            self.ref, self.best_time = filled, lap_time
            self.ref_source = "own"
            self._ref_changed()

        recent, avg = self.history[-3:], {}
        for ci in range(len(self.corners)):
            b_seg = self.best_corner.get(ci, {}).get("seg")
            vals = [h["corners"][ci]["seg"] - b_seg for h in recent
                    if ci in h["corners"] and ok(h["corners"][ci].get("seg")) and ok(b_seg)]
            if vals:
                avg[ci] = sum(vals) / len(vals)
        self.focus = []
        for ci, l in sorted(avg.items(), key=lambda kv: -kv[1])[:2]:
            if l > 0.08:
                tip = self.diagnose(per[ci], self.best_corner[ci], cue=True)
                if tip:
                    self.focus.append((ci, tip))
        drill_msg = None
        if self.drill:
            d = self.drill
            dm = per.get(d["ci"])
            if dm and ok(dm.get("seg")):
                loss = dm["seg"] - d["ref_seg"]
                d["results"].append(loss)
                d["done"] += 1
                d["tip"] = self.diagnose(dm, self.best_corner.get(d["ci"], dm), cue=True) or d["tip"]
                if d["done"] >= d["laps"]:
                    drill_msg = self._end_drill()
                else:
                    how = (f"{tenths(loss)} quicker than your best" if loss < -0.02 else
                           "right on your best" if loss < 0.03 else f"{tenths(loss)} off your best")
                    drill_msg = f"Drill lap {d['done']} of {d['laps']}, {self.turn(d['ci'])}: {how}. {d['tip']}"
            if self.drill:
                self.focus = [(self.drill["ci"], self.drill["tip"])]
        if changed or pb:
            self.save()

        will_finish_race = bool(f and (
            f.race_over
            or (f.session == "race" and f.race_laps > 0 and f.laps_done >= f.race_laps)
            or (f.session == "race" and f.time_left is not None and f.time_left <= 0.0)
        ))
        unhinged = self.cfg.get("coach_personality", DEFAULT_CONFIG["coach_personality"]) in ("apex", "almeida")
        chatty = self.cfg.get("talk_level", 1) >= 2
        excuse = ("there was a yellow flag" if lap.ctx_yellow else
                  "you were held up in traffic" if lap.ctx_traffic_s >= 2.0 else
                  "the tyres were still coming in" if since_pit == 0 else None)
        parts = [f"{fmt_time(lap_time)}."]
        if pb:
            parts.append(f"Purple lap! New personal best, {tenths(delta)} quicker.")
            pace = self.pace_pct(lap_time)
            if pace is not None:
                parts.append("That beats my target time for " + self.target_words() + "." if pace < 100.0 else
                             f"That's {pace:.1f} percent of {self.target_words()}.")
        elif excuse and delta >= 0.3:
            parts.append(f"{tenths(delta)} off your best, but {excuse}, so don't read anything into that one.")
        elif delta >= 1.2 and unhinged:
            parts.append(f"{tenths(delta)} off your best — what on earth was that lap?! Breathe, reset your eyes, and stop overdriving.")
        else:
            parts.append(f"{tenths(delta)} off your best.")
        if improved and (pb or delta <= 0.6) and not drill_msg and chatty:
            parts.append(f"Gained most in {self.turn(max(improved)[1])}.")
        if will_finish_race:
            self.say(" ".join(parts), now, force=True)
            self._set_focus(self.focus)
            return
        # one coaching point
        if drill_msg:
            parts.append(drill_msg)
        elif self.focus and not excuse:
            ci, tip = self.focus[0]
            parts.append(f"Next lap, isolate {self.turn(ci)}: {tip}")
        elif not pb and chatty:
            parts.append("Repeatable inputs. Keep stacking clean laps.")
        # extras: all of them when Chatty; otherwise at most one, every other lap, and never on an excused lap
        extras = []
        if len(lap.shift_ratios) >= 3:
            med = sorted(lap.shift_ratios)[len(lap.shift_ratios) // 2]
            if med < 0.86:
                extras.append("You're short-shifting like you're driving a school bus — wind out the rev range!"
                              if unhinged else "You're short shifting, use more of the rev range.")
        if lap.limiter_time > 1.5:
            extras.append("You're bouncing off the limiter — the engine is begging for mercy, shift earlier!"
                          if unhinged else "You're sitting on the limiter, shift a touch earlier.")
        times = [h["time"] for h in self.history[-5:] if not h.get("pit") and not h.get("invalid")]
        if len(times) >= 4 and self.lap_no % 4 == 0:
            sd = stdev(times)
            extras.append(f"Consistency is {'metronomic' if sd < 0.4 else 'all over the place — settle your markers'}, laps within {tenths(sd)}."
                          if unhinged else f"Consistency is {'good' if sd < 0.4 else 'patchy'}, laps within {tenths(sd)}.")
        crew_eng = self.crew is not None and self.crew.on("engineer")
        if lap.max_press and lap.min_press and self.key and self.key[0] == "ACC" and not crew_eng:
            if lap.max_press > 28.5:
                extras.append("Tyre pressures are high, drop them in the next stop.")
            elif lap.min_press < 25.5 and self.lap_no > 3:
                extras.append("Tyre pressures are low.")
        if crew_eng:
            pass
        elif lap.max_temp and lap.max_temp > 105:
            extras.append("Tyres are running hot, be smoother on entry.")
        elif lap.min_temp and lap.min_temp < 60 and self.lap_no > 2:
            extras.append("Tyres are still cold, lean on them a bit more.")
        if chatty:
            parts += extras
        elif extras and not excuse and self.lap_no % 2 == 0:
            parts.append(extras[0])
        if f and f.game not in RALLY_GAMES and fuel_used > 0.2 and f.fuel / fuel_used < 2.5 and not crew_eng:
            n_fl = max(1, int(f.fuel / fuel_used))
            parts.append(f"Fuel for about {'one more lap' if n_fl == 1 else f'{n_fl} more laps'}.")
        self.say(" ".join(parts), now, force=True)
        self._set_focus(self.focus)

    def _on_race_finished(self, f: Frame, now: float):
        """Register race completion, write the after-race report, and notify the driver and UI."""
        self.race_finished = True
        self.race_finished_at = now
        self._state_rev += 1
        pos_str = f"P{f.position}" + (f" of {f.cars}" if f.cars else "") if f.position else "the finish"
        n_laps = len(self.history)
        race_best = min((h["time"] for h in self.history if not h.get("pit") and not h.get("invalid")), default=None)
        rally = f.game in RALLY_GAMES
        best_str = f", best {'run' if rally else 'lap'} {fmt_time(race_best)}" if race_best else ""
        runs = (f"{n_laps} runs" if n_laps != 1 else "one run") if rally else _say_laps(n_laps)
        laps_str = f" with {runs} recorded{best_str}" if n_laps else ""
        if not f.in_pit:
            done = (f"Chequered flag! You finished {pos_str}" if f.position else
                    "That's the stage done" if f.game in RALLY_GAMES else "Chequered flag! That's the finish")
            where = ("Stop the car for your full debrief." if f.game in RALLY_GAMES else
                     "Bring the car into the pits for your full after-race debrief.")
            self.say(f"{done}{laps_str}. {where}", now, kind="urgent", force=True)
        path = self.end_session()
        done_lbl = "Stage" if rally else "Race"
        status_txt = f"{done_lbl} finished · {pos_str}" if f.position else f"{done_lbl} finished"
        self.overlay.post(
            race_finished=True,
            race_finished_status=status_txt,
            report_ready=path,
            focus=f"{done_lbl} complete  ·  {runs} recorded  ·  {'Stop the car' if rally else 'Bring car to pits'} for full debrief"
            if not f.in_pit else f"{done_lbl} complete  ·  {runs} recorded  ·  After-race report saved",
        )

    def after_race_debrief(self, f: Optional[Frame], now: float, speak: bool = True) -> str:
        """Build and speak a full, audible after-race report when the race is finished and the car is in the pits."""
        with self.lock:
            f = f or self.last_frame
            driver = self.cfg.get("driver_name") or "driver"
            track = (nice_name(f.track) if f else (nice_name(self.key[1]) if self.key else "")) or "the circuit"
            car = (nice_name(f.car) if f else (nice_name(self.key[2]) if self.key else "")) or "car"
            rally = bool((f and f.game in RALLY_GAMES) or (self.key and self.key[0] in RALLY_GAMES))
            u_sg, u_pl = ("run", "runs") if rally else ("lap", "laps")
            n_laps = len(self.history)
            clean_laps = [h["time"] for h in self.history if not h.get("pit") and not h.get("invalid")]
            all_laps = [h["time"] for h in self.history]
            times = clean_laps or all_laps
            parts = [f"Alright {driver}, {'here is your stage debrief' if rally else 'welcome back to the pits. Here is your full after-race report'} for {track} in the {car}."]
            if f and f.position:
                grid = getattr(self.crew, "grid_pos", None) if self.crew else None
                field = f" out of {f.cars} cars" if f.cars else ""
                if grid and grid != f.position:
                    diff = grid - f.position
                    move = f"gaining {diff} {'place' if diff == 1 else 'places'} from P{grid}" if diff > 0 else f"down {-diff} {'place' if diff == -1 else 'places'} from P{grid}"
                    parts.append(f"You finished P{f.position}{field}, {move} on the grid.")
                else:
                    parts.append(f"You brought it home in P{f.position}{field}.")
            if times:
                pool = [(h["time"], idx + 1) for idx, h in enumerate(self.history)
                        if not h.get("pit") and not h.get("invalid")] or \
                       [(h["time"], idx + 1) for idx, h in enumerate(self.history)]
                best_t, best_idx = min(pool)
                avg_t = sum(times) / len(times)
                sd = stdev(times) if len(times) >= 2 else 0.0
                parts.append(
                    f"Over {n_laps} {u_sg if n_laps == 1 else u_pl}, your fastest {u_sg} was {u_sg} {best_idx} with a {fmt_time(best_t)}, "
                    f"averaging {fmt_time(avg_t)}."
                )
                if self.best_time and best_t > self.best_time + 0.05:
                    parts.append(f"Your all-time best here is still the {fmt_time(self.best_time)}.")
                cons = consistency_of(self.session_clean_times())
                if cons:
                    parts.append(f"You were {cons['label']}: your clean laps varied by about {tenths(cons['sd'])}"
                                 + (f", not counting {cons['off']} slower lap{'s' if cons['off'] != 1 else ''}" if cons["off"] else "")
                                 + ".")
                elif len(times) >= 2:
                    parts.append(
                        f"Your stint consistency was {'rock solid' if sd < 0.35 else 'steady' if sd < 0.7 else 'variable'}, "
                        f"with a lap-to-lap variation of {tenths(sd)}."
                    )
                pace = self.pace_pct(best_t)
                if pace is not None:
                    tg = self.target()
                    parts.append(f"Against the target of {fmt_time(tg[0])}, {self.target_words()}, your best lap was "
                                 + ("quicker." if pace < 100.0 else f"{pace:.1f} percent, {tenths(best_t - tg[0])} off."))
                advice = pace_advice(pace, cons)
                if advice:
                    parts.append(advice)
                tb = self.theoretical_best()
                if tb and best_t - tb >= 0.08:
                    parts.append(
                        f"Putting your best corners together gives an optimal {fmt_time(tb)}, leaving {tenths(best_t - tb)} on the table."
                    )
            if self.corners and self.history:
                corner_losses = []
                total_locks = total_spins = 0
                for ci in range(len(self.corners)):
                    b = self.best_corner.get(ci, {})
                    b_seg = b.get("seg")
                    seg_sum = 0.0
                    seg_cnt = 0
                    for h in self.history:
                        cm = h["corners"].get(ci)
                        if cm is not None:
                            sg = cm.get("seg")
                            if ok(sg) and not h.get("pit"):
                                seg_sum += sg
                                seg_cnt += 1
                            if cm.get("lock"):
                                total_locks += 1
                            if cm.get("spin"):
                                total_spins += 1
                    if seg_cnt and ok(b_seg):
                        loss_avg = (seg_sum / seg_cnt) - b_seg
                        corner_losses.append((loss_avg, ci))
                corner_losses.sort(reverse=True)
                if corner_losses:
                    best_loss, best_ci = corner_losses[-1]
                    top_loss, top_ci = corner_losses[0]
                    if len(corner_losses) >= 2 and best_ci != top_ci:
                        parts.append(f"Your strongest corner was {self.turn(best_ci)}.")
                    if top_loss > 0.06:
                        issues = self.issue_counts.get(top_ci, {})
                        top_issue = max(issues.items(), key=lambda kv: kv[1])[0] if issues else None
                        if not top_issue and self.history[-1]["corners"].get(top_ci):
                            top_issue = self.diagnose(self.history[-1]["corners"][top_ci], self.best_corner.get(top_ci, {}))
                        issue_txt = f" — {top_issue[0].lower() + top_issue[1:]}" if top_issue else "."
                        second_txt = ""
                        if len(corner_losses) > 1 and corner_losses[1][0] > 0.06:
                            second_txt = f" Your next biggest time loss was {self.turn(corner_losses[1][1])}, costing {tenths(corner_losses[1][0])} per lap."
                        parts.append(
                            f"Looking at the corners, your biggest time loss was {self.turn(top_ci)}, where you gave away an average of "
                            f"{tenths(top_loss)} a lap{issue_txt}{second_txt}"
                        )
                    else:
                        parts.append("Your corner pace was right on your reference across the whole lap.")
                if total_locks or total_spins:
                    inc = []
                    if total_locks:
                        inc.append(f"{total_locks} brake {'lock-up' if total_locks == 1 else 'lock-ups'}")
                    if total_spins:
                        inc.append(f"{total_spins} exit {'wheelspin' if total_spins == 1 else 'wheelspins'}")
                    unhinged_d = self.cfg.get("coach_personality", DEFAULT_CONFIG["coach_personality"]) in ("apex", "almeida")
                    parts.append(
                        f"On car control, we logged {' and '.join(inc)} over the race — stop treating the pedals like on-off switches and let the tyres live!"
                        if unhinged_d else
                        f"On car control, we logged {' and '.join(inc)} over the race, so smoothing out the pedals will keep the tyres happier."
                    )
                elif f is not None and f.wheel_kmh is not None:
                    parts.append("Pedal discipline was clean with zero lock-ups or wheelspin logged.")
            if f and f.fuel > 0 and not rally:
                parts.append(f"You boxed with {f.fuel:.1f} {fuel_unit(f.game)} of fuel remaining.")
            path = self.end_session()
            parts.append("Your full written report is saved and ready in the Reports tab. Great drive out there.")
            report_speech = " ".join(parts)
            self.last_debrief_txt = self._save_debrief_text(path, f, parts)
            if speak:
                self.say(report_speech, now, kind="urgent", force=True)
            self.overlay.post(
                focus=f"Debrief complete  ·  {n_laps} {u_sg if n_laps == 1 else u_pl} in report",
                report_ready=path,
            )
            return report_speech

    def _save_debrief_text(self, html_path, f, parts):
        """The spoken after-race report as a text file in the reports folder, next to the session's HTML report
        (same name + _after_race.txt). Asking for the debrief again rewrites the same file."""
        try:
            if self._session_debrief_path and os.path.dirname(self._session_debrief_path) == REPORT_DIR:
                txt = self._session_debrief_path
            elif html_path:
                stem = os.path.splitext(html_path)[0]
                txt, k = stem + "_after_race.txt", 2
                while os.path.exists(txt):
                    txt, k = f"{stem}_{k}_after_race.txt", k + 1
            else:
                game, track, car = self.key or ("", "", "")
                stem = os.path.join(REPORT_DIR, _RE_SAFE_REPORT.sub(
                    "_", f"{time.strftime('%Y-%m-%d_%H%M')}_{track}_{car}"))
                txt, k = stem + "_after_race.txt", 2
                while os.path.exists(txt) or os.path.exists(stem + (".html" if k == 2 else f"_{k - 1}.html")):
                    txt, k = f"{stem}_{k}_after_race.txt", k + 1
            game = (f.game if f else (self.key[0] if self.key else "")) or ""
            track = nice_name(f.track) if f else (nice_name(self.key[1]) if self.key else "")
            car = nice_name(f.car) if f else (nice_name(self.key[2]) if self.key else "")
            head = [f"SimCoach after-race report  ·  {time.strftime('%Y-%m-%d %H:%M')}",
                    f"{game}  ·  {track}  ·  {car}".strip(" ·")]
            if f and f.position:
                head.append(f"Finished P{f.position}" + (f" of {f.cars}" if f.cars else ""))
            body = "\n\n".join(textwrap.fill(_RE_SPOKEN_TIME.sub(r"\1:\2", p_).replace("k p h", "km/h"), 100)
                                 for p_ in parts)
            os.makedirs(os.path.dirname(txt) or ".", exist_ok=True)
            tmp = txt + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(head) + "\n" + "=" * 60 + "\n\n" + body + "\n")
                os.replace(tmp, txt)
            except Exception:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
                raise
            self._session_debrief_path = txt
            self.log(f"After-race report text: {txt}")
            return txt
        except Exception as e:
            self.log(f"Couldn't save the after-race report text: {e}")
            return None

    def summary(self):
        with self.lock:
            f = self.last_frame
            laps = [round(h["time"], 3) for h in self.history[-8:]]
            corners = []
            for ci, c in enumerate(self.corners):
                b = self.best_corner.get(ci, {})
                last = self.history[-1]["corners"].get(ci) if self.history else None
                loss = round(last["seg"] - b["seg"], 3) if last and ok(last.get("seg")) and ok(b.get("seg")) else None
                corners.append({"turn": ci + 1, "lap_position_pct": round(c[0] / BINS * 100, 1),
                                "best_min_speed_kmh": round(b.get("min_speed", 0), 1),
                                "last_lap_loss_s": loss,
                                "last_issue": self.last_issue.get(ci, (None, None))[1]})
            tb = self.theoretical_best()
            clean_b = (self.best_time if (self.best_time and not self.ref_provisional and self.ref_source != "starter") else
                       min((h["time"] for h in self.history if not h.get("pit") and not h.get("invalid")), default=None))
            return {
                "status": "in a session" if self.live() else "in the garage: no sim running right now",
                "sim": f.game if f else None, "track": f.track if f else None, "car": f.car if f else None,
                "driver": self.cfg.get("driver_name"),
                "best_lap_s": round(clean_b, 3) if clean_b else None, "recent_laps_s": laps,
                "theoretical_best_s": round(tb, 3) if tb else None,
                "target_lap_s": (self.target() or (None,))[0],
                "pace_pct_of_target": round(self.pace_pct(clean_b), 1) if clean_b and self.target() else None,
                "consistency": ((lambda c_: {"spread_s": round(c_["sd"], 2), "rating": c_["label"]} if c_ else None)
                                (consistency_of(self.session_clean_times()))),
                "focus": [{"turn": ci + 1, "tip": t} for ci, t in self.focus],
                "drill": ({"turn": self.drill["ci"] + 1, "lap": self.drill["done"] + 1, "of": self.drill["laps"]}
                          if self.drill else None),
                "drills_done": list(self.drills_done),
                "race_start": getattr(self, "last_start", None),
                "corners": corners,
                "fuel_l": round(f.fuel, 1) if f else None,
                "tyre_core_temps_c": [round(x) for x in f.tyre_temps] if f and f.tyre_temps else None,
                "track_length_m": self.track_len,
                "lap_time_consistency_s": round(stdev([h["time"] for h in self.history[-6:] if not h.get("pit") and not h.get("invalid")] or [h["time"] for h in self.history[-6:]]), 3),
                "coach_personality": self.cfg.get("coach_personality", DEFAULT_CONFIG["coach_personality"]),
                "recommended_race_setup": self.last_setup_briefing,
                "setup_sheet": [" ".join(x for x in it if x) for it in (self.last_setup_sheet or {}).get("items", [])] or None,
                "applied_setup": self.applied_setup,
                "recent_issue_counts": {f"turn {ci + 1}": v for ci, v in self.issue_counts.items()},
                "tyre_pressures_psi": [round(x, 1) for x in f.tyre_press] if f and f.tyre_press else None,
                "race_finished": self.race_finished,
                "car_ahead": f.car_ahead if f else None,
                "car_behind": f.car_behind if f else None,
            }




CREW_ROLES = [("engineer", "Race engineer", "en-GB-ThomasNeural"),
              ("strategist", "Strategist", "en-US-AndrewNeural"),
              ("spotter", "Spotter", "en-AU-WilliamNeural")]
_CREW_DEFAULT_VOICES = {r: v for r, _, v in CREW_ROLES}
_ROLE_ON = {r: f"{r}_on" for r, _, _ in CREW_ROLES}
WHEELS = ["front left", "front right", "rear left", "rear right"]
BRIEFING_MODES = [("Full once a day, then short", "daily"), ("Full every session", "always"), ("Off (sheet only)", "off")]
CREW_UPDATES = [("Every lap", "every"), ("Every 2 laps", "every2"), ("Important calls only", "important")]
CREW_CHATTER = [("Off", "off"), ("Normal", "normal"), ("Lots", "lots")]
CREW_LANGUAGE = [("Clean", "clean"), ("Salty (swearing, slang)", "salty")]
SPOTTER_GAMES = ["AC", "ACC", "LMU", "rFactor 2", "AMS2", "RaceRoom", "F1 25"]
SPOT_PHRASES = ["Car left.", "Car right.", "Three wide, you're in the middle.", "Clear left.", "Clear right.",
                "Clear all round.", "Still there."]


def _say_laps(n):
    return "one lap" if n == 1 else f"{n} laps"


def _laps_left(x):
    """A fuel range for speech: "about one lap", "about 4 laps", "less than a lap"."""
    n = int(round(x))
    return "less than a lap" if x < 0.5 else _say_laps(n)


CREW_PERSONAS = {
    "engineer": "the race engineer: calm and dry British humour, technical, reassuring, a steady hand",
    "strategist": "the race strategist: upbeat American, competitive, loves numbers and a good battle",
    "spotter": "the spotter: laid-back Australian, quick, cheeky, short sentences",
}
CHATTER_EVENTS = {
    "start": "the session is about to start, say something to get the driver in the mood",
    "gain": "the driver just gained a position",
    "loss": "the driver just lost a position",
    "contact": "the car just took a hit and has some damage",
    "last_lap": "it's the last lap of the race",
    "finish": "the driver just crossed the finish line",
    "pb": "the driver just set a personal best lap",
    "quiet": "a quiet moment on a straight; light, friendly radio banter about the race, the track or the car",
    "quiet_slow": ("a quiet moment on a straight; the driver is still finding their pace (well off a quick lap or their "
                   "own best), so be encouraging and patient: do not praise the pace or call the laps quick"),
}
CANNED = {
    "start": {"any": ["Right, {driver}, {track} in the {car}. Let's have some fun out there.",
                      "Whole crew's on the radio, {driver}. Deep breath, nice and tidy into turn one.",
                      "Lovely day for it at {track}. Let's go racing.",
                      "Radio's quiet, tyres are cold, the {car} is ready. Your move, {driver}."]},
    "gain": {"spotter": ["Lovely move, mate. Didn't see that coming, neither did he.",
                         "Ha! Sent it. Nice one.", "That's how it's done. Up you go.",
                         "Clean pass. He's in your mirrors now, not the other way round."],
             "strategist": ["Now we're talking. Keep that momentum.", "Beautiful. That's the kind of move that wins races.",
                            "Up we go. Next car's yours too."]},
    "loss": {"engineer": ["Shake it off. Long way to go, he'll come back to you.", "No harm done. Reset and go again.",
                          "Plenty of race left. Settle back into your rhythm."],
             "strategist": ["Lost one, we'll get it back. Look for the run into the next heavy stop.",
                            "Don't sweat it. Keep it clean, the pace is there."]},
    "contact": {"spotter": ["Ooh, that was a bit of a bump. You alright?", "Rubbing's racing, mate. Mostly.",
                            "Bit of contact there. Car still pointing the right way, good."]},
    "last_lap": {"engineer": ["Last one. Everything's holding together, enjoy it.",
                              "Final lap. Nice and neat, bring her home."]},
    "finish": {"strategist": ["Chequered flag! Great job out there, {driver}.", "And that's the flag. Proper drive, that.",
                              "Over the line. Good racing today, {driver}."]},
    "pb": {"engineer": ["Lovely lap. The car liked that one.", "Now that was tidy. Purple, as they say."]},
    "quiet": {"engineer": ["Car's looking healthy on the data. Nice work.", "Tyres and temps are behaving. Just keep doing what you're doing.",
                           "Quiet one on the pit wall. That's a good thing."],
              "strategist": ["Pace is solid, {driver}. Keep stacking these laps.", "Nice rhythm. This is where races are won.",
                             "Good stuff. Every tenth counts out there."],
              "spotter": ["Clear around you. Enjoy the view at {track}.", "All quiet out here. Nice and smooth.",
                          "Nobody near you, mate. Just you and the track."]},
}
# a quiet moment while the driver is still well off the pace: no praise for the pace
CANNED["quiet_slow"] = {
    "engineer": CANNED["quiet"]["engineer"],
    "strategist": ["Plenty of laps to build it up, {driver}. One corner at a time.",
                   "No rush. Clean laps first, the speed follows.", "Keep working at it, the time is in there."],
    "spotter": CANNED["quiet"]["spotter"],
}


CANNED_SALTY = {
    "start": {"any": ["Right, {driver}, let's go kick some arse at {track}.",
                      "Helmet on, brain on. Send it, just not too bloody hard into turn one.",
                      "Time to make these bastards earn it, {driver}."]},
    "gain": {"spotter": ["Fucking sent it! Beautiful.", "Ha! He didn't know what hit him, mate.", "Get in! Bloody lovely move."],
             "strategist": ["Hell yes. Next victim's up the road.", "Damn, that was clean. Go get the next one."]},
    "loss": {"engineer": ["Bollocks. Shake it off, plenty of race left.", "Bit of a shit one, that. Reset and go again."],
             "strategist": ["Damn it. We'll get that bastard back.", "Ah, hell. He's not getting away, keep on him."]},
    "contact": {"spotter": ["Ooft, that was a hit. Fucking hell, you alright?", "Bit of argy-bargy there. Rubbing's racing, mate.",
                            "Bloody hell, he gave you a whack."]},
    "last_lap": {"engineer": ["Last lap. Don't you dare bin it now.", "Final lap. Keep your shit together and bring her home."]},
    "finish": {"strategist": ["Chequered flag! Hell of a drive, {driver}.", "Done and dusted. Bloody good racing, mate."]},
    "pb": {"engineer": ["Bloody hell, that was quick.", "Holy shit, purple lap. Nicely done."]},
    "quiet": {"engineer": ["Data's looking sweet. Bloody tidy work.", "Car's happy, I'm happy. Keep hammering."],
              "strategist": ["Pace is damn good, {driver}. Keep stacking them.", "Hell of a rhythm. Keep it rolling."],
              "spotter": ["Bugger all around you, mate. Enjoy the view.", "Nobody about. Just you and the bloody track."]},
}


_RE_NAME_SPLIT = re.compile(r"[_\s]+")
_RE_MODEL_YEAR = re.compile(r"(19|20)\d\d")
_MOD_PREFIXES = frozenset(("ks", "rss", "vrc", "urd", "acf", "rt"))
_UPPER_TOKENS = frozenset(("bmw", "amg", "gt", "gte", "lmp", "dtm", "rs", "srs", "gtr", "gtd", "vw"))


@lru_cache(maxsize=256)
def nice_name(raw):
    """Readable track/car names from game IDs: 'ks_bmw_m4_gt3_2022' -> 'BMW M4 GT3', 'spa' -> 'Spa'."""
    if not raw:
        return ""
    s = str(raw).strip()
    words = [w for w in _RE_NAME_SPLIT.split(s) if w]
    if words and words[0].lower() in _MOD_PREFIXES:
        words = words[1:]
    out = []
    n_words = len(words)
    for w in words:
        lw = w.lower()
        if n_words > 1 and _RE_MODEL_YEAR.fullmatch(lw):
            continue
        if lw in _UPPER_TOKENS or any(ch.isdigit() for ch in lw):
            out.append(lw.upper())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out) or s



class Crew:
    """Engineer (fuel, tyres, damage), strategist (race plan, pit window, positions, gaps, laps to go, weather)
    and spotter (cars alongside), each with their own voice and personality.
    - Introduce themselves when a session starts.
    - After every lap (from lap one): a short engineer report and, in races, a strategist report.
    - Alerts the moment something happens (fuel, box, damage, positions, last lap, rain).
    - Casual chatter: reactions and light banter on quiet straights (the AI when a key is set, built-in lines otherwise).
    News waits for the coach to finish and for a straight; chatter only ever fills quiet moments; the spotter cuts in."""

    def __init__(self, cfg, voice, overlay, log=print, coach=None):
        self.cfg, self.voice, self.overlay, self.log, self.coach = cfg, voice, overlay, log, coach
        self.key = None
        self._p_lock = threading.Lock()
        self.pending = deque()
        self.last_chat = -999.0
        self.last_spoken = 0.0
        self._recent_lines = deque(maxlen=40)
        self.reset()

    def voice_for(self, role):
        if role == "coach":
            return self.cfg.get("voice")
        return self.cfg.get(f"{role}_voice") or _CREW_DEFAULT_VOICES[role]

    def on(self, role):
        if role == "coach":
            return self.cfg.get("talk_level", 1) > 0
        return bool(self.cfg.get(_ROLE_ON[role], True))

    def reset(self):
        self._slow_t = -1.0
        with self._p_lock:
            self.pending.clear()
        self.last_laps = None
        self.session = None
        self.fuel_at_line = None
        self.fuel_laps = []
        self.energy_at_line = None
        self.energy_laps = []
        self.temps = {"base": {}, "lap": {}, "said": {}, "hot_t": {}}
        self.tl = {"last": None, "t": -99.0}
        self.lap_times = []
        self.best_lap = None
        self.lap_pit = False
        self.lap_invalid = False
        self._prev_pct = self._prev_cur = None
        self.prev_fuel = None
        self.stint = 0
        self._fill_base, self._fill_counted = None, False
        self._stop_t, self._stop_counted = None, False
        self._on_track = False
        self.report_due = None
        self.grid_pos = None
        self.moving_since = None
        self.race_finished = False
        self.eng = {"said": set(), "wear_mark": 0, "dmg": None, "dmg_parts": None, "dmg_t": -99.0, "wear_dir": None,
                    "heavy": False}
        self.strat = {"said": set(), "pos": None, "pos_new": None, "pos_t": 0.0, "gaps": [], "rain": None,
                      "boxed_lap": None, "plan": None, "best_lap": None, "wet": False}
        self.spot = {"hist": deque(), "left": False, "right": False, "left_t": 0.0, "right_t": 0.0, "since": None,
                     "still": False, "start": None}
        self.flg = {"cur": None, "since": 0.0, "said": None, "said_t": {}, "caution": None}

    def say(self, role, text, now, urgent=False, chat=False):
        if not text or not self.on(role):
            return
        if urgent:
            self.voice.say(text, now, "urgent", voice=self.voice_for(role), who=role.upper())
            self.overlay.post(tip=f"{role.title()}: {text}")
            self.last_spoken = now
        else:
            with self._p_lock:
                if not any(p[2] == text for p in self.pending):
                    self.pending.append((now, role, text, chat))

    def _flush(self, now):
        if not self.pending:
            return
        with self._p_lock:
            while self.pending and now - self.pending[0][0] > (20 if self.pending[0][3] else 45):
                self.pending.popleft()
            if not self.pending:
                return
            created, role, text, chat = self.pending[0]
            idle = self.voice.idle(now)
            if not idle:
                return
            if chat:
                if not (self.voice.on_straight.is_set() or self.race_finished):
                    return
            else:
                if not (self.voice.on_straight.is_set() or self.race_finished or now - created > 6):
                    return
            self.pending.popleft()
        self.voice.say(text, now, "chat" if chat else "info", voice=self.voice_for(role), who=role.upper())
        self.overlay.post(tip=f"{role.title()}: {text}")
        self.last_spoken = now

    def chatter_level(self):
        return self.cfg.get("crew_chatter", "normal")

    def chatter(self, role, event, facts, now, force=False, reaction=False):
        """One casual line in character. Rate-limited (reactions to something that just happened get through
        sooner than idle banter); the AI writes it when a key is set, else a built-in line."""
        level = self.chatter_level()
        if level == "off" or not self.on(role):
            return
        gap = 8 if reaction else 20 if level == "lots" else 40
        if not force and now - self.last_chat < gap:
            return
        self.last_chat = now
        gen = getattr(self, "_gen", 0)
        line = self._canned(role, event, facts)
        if not ai_key(self.cfg):
            self.say(role, line, now, chat=True)
            return

        def work():
            text = None
            try:
                sys_msg = (f"You are {CREW_PERSONAS[role]} on {facts.get('driver') or 'the driver'}'s sim racing team, talking "
                           f"on team radio. Reply with ONE short casual radio line, at most 14 words: natural, warm, a bit of "
                           f"personality and humour. Only use the facts given; never invent positions, times, gaps or names. "
                           f"No driving instructions, no emojis, no quotation marks."
                           + (" Swearing and slang are welcome: the driver likes rough, good-natured banter. Keep it "
                              "friendly ribbing, no slurs, nothing hateful." if self.salty() else " Keep it clean."))
                msg = f"Moment: {CHATTER_EVENTS.get(event, event)}. Facts: {json.dumps(facts)}"
                text = ai_chat(self.cfg, [{"role": "system", "content": sys_msg}, {"role": "user", "content": msg}],
                               max_tokens=40)
                text = text.strip().strip('"').replace("*", "")
                if len(text.split()) > 22:
                    text = None
            except Exception as e:
                self.log(f"Crew chatter offline ({type(e).__name__}); using built-in lines.")
            if gen == getattr(self, "_gen", 0):
                self.say(role, text or line, now, chat=True)
        threading.Thread(target=work, daemon=True, name="crew-chatter").start()

    def salty(self):
        return self.cfg.get("crew_language", "clean") == "salty"

    def _canned(self, role, event, facts):
        pool = list(CANNED.get(event, {}).get(role) or CANNED.get(event, {}).get("any") or [])
        if self.salty():
            pool += CANNED_SALTY.get(event, {}).get(role) or CANNED_SALTY.get(event, {}).get("any") or []
        fresh = [p for p in pool if p not in self._recent_lines] or pool
        if not fresh:
            return None
        line = random.choice(fresh)
        self._recent_lines.append(line)
        try:
            return line.format(**facts)
        except Exception:
            return line

    def facts(self, f):
        d = {"driver": self.cfg.get("driver_name") or "driver", "track": nice_name(f.track), "car": nice_name(f.car),
             "session": f.session or "session", "game": f.game}
        if f.position:
            d["position"] = f.position
        if f.cars:
            d["cars"] = f.cars
        togo = self.laps_to_go(f)
        if togo is not None:
            d["laps_to_go"] = math.ceil(togo)
        if self.grid_pos:
            d["started"] = self.grid_pos
        if f.gap_ahead is not None:
            d["gap_ahead_s"] = round(f.gap_ahead, 1)
        if f.gap_behind is not None:
            d["gap_behind_s"] = round(f.gap_behind, 1)
        if f.car_ahead:
            d["car_ahead"] = f.car_ahead
        if f.car_behind:
            d["car_behind"] = f.car_behind
        if self.lap_times:
            d["last_lap"] = fmt_time(self.lap_times[-1]).replace(" ", ":")
        return d

    def _nearest_car_desc(self, f: Frame, which: str) -> str:
        """Format the nearest car ahead or behind with driver name, position, car driven, and distance in metres."""
        info = f.car_ahead if which == "ahead" else f.car_behind
        gap = f.gap_ahead if which == "ahead" else f.gap_behind
        pos_num = (info.get("position") if info else None) or (
            (f.position - 1 if which == "ahead" else (f.position + 1 if not f.cars or f.position < f.cars else None))
            if f.position and (which == "behind" or f.position > 1) else None
        )
        name = (info.get("name") or "").strip() if info else ""
        car_model = (info.get("car") or "").strip() if info else ""
        dist_m = info.get("distance_m") if info else None
        if dist_m is None and gap is not None and gap > 0:
            dist_m = round(max(1.0, gap * max(f.speed, 60.0) / 3.6))
        who_parts = []
        if name:
            who_parts.append(name)
        if pos_num:
            who_parts.append(f"in P{pos_num}" if name else f"P{pos_num}")
        if car_model:
            who_parts.append(f"driving the {car_model}")
        who = " ".join(who_parts)
        dm_i = int(round(dist_m)) if dist_m is not None else 0
        dist_str = f"{dm_i} {'metre' if dm_i == 1 else 'metres'}" if dist_m is not None else ""
        if who and dist_str:
            return f"{who}, {dist_str}"
        return who or dist_str

    def fuel_per_lap(self):
        xs = self.fuel_laps[-4:]
        return sorted(xs)[len(xs) // 2] if xs else None

    def energy_per_lap(self, f=None):
        """Virtual energy used per green lap (median of the last four), else the sim's own figure."""
        xs = self.energy_laps[-4:]
        if xs:
            return sorted(xs)[len(xs) // 2]
        return f.energy_lap if f is not None and f.energy_lap else None

    def avg_lap(self):
        xs = sorted(self.lap_times[-5:])
        return xs[len(xs) // 2] if xs else None

    def laps_to_go(self, f):
        """Distance left in the race, in laps, from where the car is now (None if unknown)."""
        if f.session != "race":
            return None
        if f.race_laps:
            return max(0.0, f.race_laps - f.laps_done - f.pct)
        lap = self.avg_lap()
        if f.time_left is not None and lap:
            return max(0.0, math.ceil(f.pct + f.time_left / lap) - f.pct)
        return None

    def every(self):
        """Post-lap reports: every lap (default), every 2 laps, or important calls only."""
        return {"every": 1, "every2": 2, "important": 0}.get(self.cfg.get("crew_updates", DEFAULT_CONFIG["crew_updates"]), 1)

    def _new_race(self, f):
        """A new session or a restarted race: clear the per-race calls, keep what we learned about fuel and pace."""
        self._gen = getattr(self, "_gen", 0) + 1
        with self._p_lock:
            self.pending.clear()
        self.race_finished = False
        self.best_lap = None
        self.flg = {"cur": None, "since": 0.0, "said": None, "said_t": {}, "caution": None}
        self.last_laps = f.laps_done
        self.report_due = None
        self.grid_pos = f.position if f.session == "race" and f.position else None
        self.moving_since = None
        self.stint = 0
        self.fuel_at_line = f.fuel if (f.fuel > 0 and f.pct < 0.08) else None
        self.energy_at_line = f.energy if (f.energy is not None and f.energy > 0 and f.pct < 0.08) else None
        self.temps["lap"].clear(); self.temps["said"].clear(); self.temps["hot_t"].clear()
        self.tl = {"last": None, "t": -99.0}
        self.lap_pit = False
        self.lap_invalid = False
        self._prev_pct = self._prev_cur = None
        self._fill_base, self._fill_counted = None, False
        self._stop_t, self._stop_counted = None, False
        self._on_track = False
        self.prev_fuel = f.fuel
        E = self.eng
        E["said"], E["wear_mark"], E["heavy"], E["dmg"], E["dmg_parts"] = set(), 0, False, None, None
        E["wear_last"] = None
        S = self.strat
        S["said"], S["pos"], S["pos_new"], S["gaps"] = set(), None, None, []
        S["boxed_lap"], S["plan"], S["rain"], S["wet"] = None, None, None, False

    def _new_stint(self, f):
        """After a pit stop: fresh fuel/tyre calls and a new fuel plan."""
        self.fuel_at_line, self.stint = (f.fuel if f.fuel > 0 else None), self.stint + 1
        self.energy_at_line = None
        self.eng["said"] = {x for x in self.eng["said"] if not x.startswith(("energy", "elimit", "eshort"))}
        if f.pct >= 0.08:
            self.lap_pit = True
        self.eng["said"] = {x for x in self.eng["said"] if not x.startswith("fuel")}
        S = self.strat
        S["said"].discard("plan")
        S["boxed_lap"], S["plan"] = f.laps_done, None

    def _track_stops(self, f, now, moving):
        """Refuels (fuel climbs a little each frame in most sims) and tyre/repair-only stops (stationary in the box).
        Each pit visit starts at most one new stint."""
        if not f.in_pit:
            self._stop_t, self._stop_counted = None, False
            if moving:
                self._on_track = True
        elif self._on_track:
            if f.speed < 1.0:
                if self._stop_t is None:
                    self._stop_t = now
                elif now - self._stop_t >= 2.0 and not self._stop_counted:
                    self._stop_counted = True
                    self._new_stint(f)
            else:
                self._stop_t = None
        fu, pf = f.fuel, self.prev_fuel
        if not self._on_track:
            if fu > 0:
                self.fuel_at_line = fu
            if f.energy is not None and f.energy > 0:
                self.energy_at_line = f.energy
            pf = None
        if pf is not None:
            if fu > pf + 0.005:
                if self._fill_base is None:
                    self._fill_base = pf
                if not self._fill_counted and fu - self._fill_base > 1.0:
                    self._fill_counted = True
                    if not (f.in_pit and self._stop_counted):
                        self._new_stint(f)
                    if f.in_pit:
                        self._stop_counted = True
                if self._fill_counted:
                    self.fuel_at_line = fu
            elif fu < pf - 0.0005 and self._fill_base is not None:
                self._fill_base, self._fill_counted = None, False
        self.prev_fuel = fu

    def update(self, f, now):
        key = (f.game, f.track, f.car)
        new_key = key != self.key
        if new_key:
            self.key = key
            self.reset()
            if self.on("spotter") and f.others is not None:
                for ph in SPOT_PHRASES:
                    self.voice.prefetch(ph, self.voice_for("spotter"))
        if new_key or f.session != self.session:
            was_ses = self.session
            self.session = f.session
            if f.session is not None or was_ses is not None:
                self._new_race(f)
            self.intros(f, now)
        moving = f.speed > 10
        if moving and self.moving_since is None:
            self.moving_since = now
        same_lap = self.last_laps is None or f.laps_done <= self.last_laps
        if f.in_pit and moving and same_lap:
            self.lap_pit = True
        if (f.off_track or f.lap_invalid) and same_lap:
            self.lap_invalid = True
        elif (same_lap and self.lap_invalid and self.coach is not None and not self.coach.lap.invalid
              and not f.off_track and not f.lap_invalid):
            self.lap_invalid = False
        if (f.restart or (self.last_laps == f.laps_done and self._prev_pct is not None
                and abs(f.pct - self._prev_pct) > 0.2 and f.cur_time < self._prev_cur - 2.0
                and not (self._prev_pct > 0.88 and f.pct < 0.12))):
            self.fuel_at_line = f.fuel if (f.fuel > 0 and f.pct < 0.08) else None
            self.energy_at_line = f.energy if (f.energy is not None and f.energy > 0 and f.pct < 0.08) else None
            self.lap_pit = f.in_pit and moving
            self.lap_invalid = bool(f.off_track or f.lap_invalid)
        self._prev_pct, self._prev_cur = f.pct, f.cur_time
        if self.fuel_at_line is None and f.fuel > 0 and f.pct < 0.08:
            self.fuel_at_line = f.fuel
        if self.energy_at_line is None and f.energy is not None and f.energy > 0 and f.pct < 0.08:
            self.energy_at_line = f.energy
        self._track_stops(f, now, moving)
        if f.energy is not None and self.energy_at_line is not None and f.energy > self.energy_at_line + 0.05:
            self.energy_at_line = None
        line = self.last_laps is not None and f.laps_done > self.last_laps
        if self.last_laps is not None and f.laps_done < self.last_laps:
            if f.session == "race" and not f.race_over and (f.laps_done == 0 or self.race_finished):
                self._new_race(f)
            else:
                self.fuel_at_line = f.fuel if f.fuel > 0 else None
                self.energy_at_line = None
                self.lap_pit = f.in_pit and moving
                self.lap_invalid = bool(f.off_track or f.lap_invalid)
                self.report_due = None
            self.last_laps = f.laps_done
        elif self.last_laps is None:
            self.last_laps = f.laps_done
        if line:
            jump = f.laps_done - self.last_laps
            self.last_laps = f.laps_done
            if self.fuel_at_line is not None and f.fuel > 0 and not self.lap_pit and jump == 1:
                used = self.fuel_at_line - f.fuel
                if 0.05 < used < 60:
                    self.fuel_laps.append(used)
            self.fuel_at_line = f.fuel if f.fuel > 0 else None
            if f.energy is not None:
                ea = self.energy_at_line
                if ea is not None and not self.lap_pit and jump == 1 and 0.002 < ea - f.energy < 0.6:
                    self.energy_laps.append(ea - f.energy)
                self.energy_at_line = f.energy
            self._temps_lap(f)
            if f.last_time > 10 and not self.lap_pit:
                if not self.lap_invalid:
                    if self.best_lap is not None and f.last_time < self.best_lap - 0.05:
                        self.chatter("engineer", "pb", self.facts(f), now, reaction=True)
                    if self.best_lap is None or f.last_time < self.best_lap:
                        self.best_lap = f.last_time
                self.lap_times.append(f.last_time)
            self.lap_pit = f.in_pit and moving
            self.lap_invalid = bool(f.off_track or f.lap_invalid)
            self.report_due = now + 4.0
        coach_fin = bool(self.coach is not None and self.coach.race_finished)
        coach_new_fin = coach_fin and not getattr(self, "_coach_fin", False)
        self._coach_fin = coach_fin
        race_over = bool(
            f.race_over
            or (f.session == "race" and f.race_laps > 0 and f.laps_done >= f.race_laps)
            or (f.session == "race" and f.time_left is not None and f.time_left <= 0.0 and line)
            or (coach_new_fin and (f.session == "race" or f.game in RALLY_GAMES))
        )
        if race_over and not self.race_finished:
            self.race_finished = True
            self.report_due = None
            self._on_race_finish(f, now)
        elif (self.race_finished and f.session == "race" and f.laps_done == 0 and not f.race_over
              and (f.time_left is None or f.time_left > 0.0)):
            self._new_race(f)
        try:
            if not self.race_finished:
                self.engineer(f, now, line)
                self.strategist(f, now, line)
                if self.report_due is not None and now >= self.report_due:
                    self.report_due = None
                    self.reports(f, now)
                self.spotter(f, now)
                self.flags(f, now)
                self.banter(f, now)
        except Exception as e:
            self.log(f"Crew error: {e}")
        self._flush(now)

    def _on_race_finish(self, f, now):
        """Crew registration and radio calls when the driver finishes a race."""
        S = self.strat
        S["said"].add("finish")
        driver = self.cfg.get("driver_name") or "mate"
        if self.on("strategist"):
            if f.position == 1:
                msg = f"Chequered flag, P1! You won the race, {driver}!"
            elif f.position:
                d = (self.grid_pos - f.position) if self.grid_pos else 0
                gain = f", up {d} from the start" if d > 0 else f", down {-d} from the start" if d < 0 else ""
                msg = f"Chequered flag! P{f.position} at the line{gain}. Great drive, {driver}."
            elif f.game in RALLY_GAMES:
                msg = f"That's the stage done, {driver}."
            else:
                msg = f"Chequered flag! Race complete, {driver}."
            self.say("strategist", msg, now, urgent=True)
        if self.on("engineer"):
            best_txt = f" Best lap was {fmt_time(self.best_lap)}." if self.best_lap else ""
            self.say("engineer", f"Good stint out there.{best_txt} Bring her back to the pits.", now)
        self.chatter("strategist", "finish", self.facts(f), now, force=True, reaction=True)

    def _first_session_today(self, f):
        """True for the first session today with this car at this track (and remembers it)."""
        d = self.cfg.get("briefed")
        if not isinstance(d, dict):
            d = self.cfg["briefed"] = {}
        key, today = f"{f.game}|{f.track}|{f.car}", time.strftime("%Y-%m-%d")
        if d.get(key) == today:
            return False
        for k in [k for k, v in d.items() if v != today]:
            d.pop(k, None)
        d[key] = today
        if f.game != "TEST":
            save_config(self.cfg)
        return True

    def intros(self, f, now):
        """Session start. The first session today with this car and track gets the lot: intros, the full strategist +
        coach setup briefing and the sheet. Later sessions get one short strategist line (say "full briefing" for
        the rest) and the sheet, without repeating the intros and banter."""
        fx = self.facts(f)
        track, car = fx["track"], fx["car"]
        mode = self.cfg.get("briefing_mode", "daily")
        full = self._first_session_today(f) or mode == "always"
        self._short_lines = ()
        if full:   # short, and goes first so the briefing that follows has some context
            self.say("engineer", f"Engineer on the radio. The {car} is ready to go. I'll keep you posted on fuel, tyres and damage.",
                     now, urgent=True)
        if self.coach is not None:
            if full and mode != "off":
                self.coach.collaborate_race_setup(f, now, speak=True, session_start=True)
            else:
                self.coach.collaborate_race_setup(f, now, speak=False, use_openai=False, session_start=True)
                if mode != "off":
                    sh = self.coach.last_setup_sheet or {}
                    fuel = next((f"{st.lower()} {ch}" for ar, st, ch in sh.get("items") or [] if ar == "Fuel" and st), None)
                    where = "on your screen" if self.cfg.get("sheet_autopop", True) else "on the overlay's setup button"
                    line = (f"Same plan as your earlier session here{f', {fuel}' if fuel else ''}. "
                            f"Setup sheet's {where}. Say full briefing for the rest.")
                    self._short_lines = (line,)
                    self.say("strategist", line, now, urgent=True)
        elif f.session == "race":
            mins = max(1, round(f.time_left / 60)) if f.time_left else 0
            length = (_say_laps(f.race_laps) if f.race_laps else
                      ("1 minute" if mins == 1 else f"{mins} minutes") if f.time_left else "this race")
            grid = f" You start P{f.position}" + (f" of {f.cars}." if f.cars else ".") if f.position else ""
            self.say("strategist", f"Strategist here. {length} at {track}.{grid} I'll call positions, gaps and the plan.", now)
        if not full:
            return
        if f.session in ("practice", "qualifying"):
            self.say("strategist", f"Strategist here. I'll track your times and position this {f.session}.", now)
        if f.game not in RALLY_GAMES:
            if f.others is not None:
                self.say("spotter", "Spotter's up in the stand. I'll call cars alongside.", now)
            elif f.game == "AC":
                self.say("spotter", "Spotter here, but the game isn't showing me the other cars. "
                                    "Switch on the CrewChiefEx app in Content Manager and I'm on it.", now)
        if f.session != "race":
            self.chatter(random.choice(["engineer", "strategist"]), "start", fx, now, force=True)

    def reports(self, f, now):
        n = self.every()
        lap_no = f.laps_done
        if not n or lap_no < 1 or lap_no % n:
            return
        if self.on("engineer"):
            self.say("engineer", self.engineer_report(f), now)
        if self.on("strategist") and f.session in ("race", "practice", "qualifying"):
            self.say("strategist", self.strategist_report(f), now)

    def engineer_report(self, f):
        parts = []
        fpl, epl = self.fuel_per_lap(), self.energy_per_lap(f) if f.energy is not None else None
        if fpl and f.fuel > 0:
            ebit = f" Virtual energy {f.energy * 100:.0f} percent, about {_laps_left(f.energy / epl)}." if (epl and f.energy / epl < f.fuel / fpl - 0.3) else ""
            parts.append(f"Fuel's {fpl:.1f} a lap, about {_laps_left(f.fuel / fpl)} in the tank.{ebit}")
        elif epl and f.energy is not None:
            parts.append(f"Virtual energy {f.energy * 100:.0f} percent, about {_laps_left(f.energy / epl)}.")
        if f.tyre_temps:
            t = f.tyre_temps
            fr, rr = (t[0] + t[1]) / 2, (t[2] + t[3]) / 2
            mood = (" Running hot, ease the entries." if max(t) > 105 else
                    " Still cold, lean on them." if min(t) < 60 else " Nicely in the window.")
            parts.append(f"Tyres {fr:.0f} front, {rr:.0f} rear.{mood}")
        if f.tyre_press:
            p = f.tyre_press
            parts.append(f"Pressures {(p[0] + p[1]) / 2:.1f} front, {(p[2] + p[3]) / 2:.1f} rear.")
        wear = self._wear_pct(f)
        if wear and max(wear) >= 20:
            w = max(range(4), key=lambda k: wear[k])
            parts.append(f"{WHEELS[w].capitalize()} is the most worn, {wear[w]:.0f} percent.")
        if self.eng["dmg"]:
            parts.append("Damage is logged, car still looks okay to run." if not self.eng["heavy"] else
                         ("Damage is heavy, nurse it to the finish." if f.game in RALLY_GAMES else "Damage is heavy, consider the pits."))
        return " ".join(parts[:3]) or "All systems look good."

    def tyre_report(self, f):
        """Asked over the radio: temperatures, pressures and wear, from whatever this sim gives."""
        parts = []
        if f.tyre_temps:
            t = f.tyre_temps
            mood = ("running hot, ease the entries" if max(t) > 105 else
                    "still cold, lean on them" if min(t) < 60 else "nicely in the window")
            parts.append(f"Temps {(t[0] + t[1]) / 2:.0f} front, {(t[2] + t[3]) / 2:.0f} rear, {mood}.")
        if f.tyre_press:
            p = f.tyre_press
            parts.append(f"Pressures {(p[0] + p[1]) / 2:.1f} front, {(p[2] + p[3]) / 2:.1f} rear.")
        wear = self._wear_pct(f)
        if wear:
            w = max(range(4), key=lambda k: wear[k])
            parts.append(f"{WHEELS[w].capitalize()} is the most worn, {wear[w]:.0f} percent." if wear[w] >= 5
                         else "Wear's barely started.")
        return " ".join(parts) or "This sim isn't giving me tyre data."

    def damage_report(self, f):
        """Asked over the radio: is the car damaged, and does it need the pits."""
        rally = f.game in RALLY_GAMES
        if f.damage is not None:
            if f.damage < 0.02:
                return "No damage, the car's clean."
            if f.damage >= 0.5:
                return "Damage is heavy. Nurse the car to the finish." if rally else "Damage is heavy. Box and get it fixed."
            if f.damage >= 0.35:
                return "Moderate damage, it'll cost you time." if rally else "Moderate damage, it'll cost you lap time. Think about the pits."
            return "Light damage, the car should be fine to run."
        if f.damage_parts:
            names = ["at the front", "at the rear", "on the left", "on the right", "underneath"]
            parts = [max(0.0, x) for x in f.damage_parts]
            hit = [names[k] for k in sorted(range(5), key=lambda k: -parts[k]) if parts[k] > 1.0]
            if not hit:
                return "No damage, the car's clean."
            where = " and ".join(hit[:2])
            return ((f"Heavy damage {where}, nurse it to the finish." if rally else f"Damage {where}. It's a lot, think about the pits.")
                    if sum(parts) >= 18.0 else f"Some damage {where}, the car should be fine to run.")
        return "This sim doesn't tell me about damage."

    def fuel_need(self, f):
        """Asked over the radio: how much fuel to the flag, and how much to add if we're short."""
        if f.game in RALLY_GAMES:
            return "There are no fuel stops on a rally stage."
        if f.fuel <= 0:
            return "No fuel data from this sim."
        fpl = self.fuel_per_lap()
        if not fpl:
            return "Need a lap or two to work out the fuel."
        togo = self.laps_to_go(f)
        if togo is None:
            return f"About {_laps_left(f.fuel / fpl)} in the tank at {fpl:.1f} a lap."
        short = togo * fpl + 0.3 * fpl - f.fuel
        u = fuel_unit(f.game)
        if short <= 0:
            return f"You've got enough, about {f.fuel - togo * fpl:.1f} {u} spare at the flag."
        if f.game in NO_REFUEL_GAMES:
            return (f"We're {short:.1f} {u} short and there's no refuelling. "
                    f"Lift and coast, save {short / max(togo, 1):.2f} a lap.")
        if f.fuel_cap > 1.0 and short > f.fuel_cap - 0.5:
            return f"We're {short:.0f} {u} short, that's more than one tank: {math.ceil(short / (f.fuel_cap - 0.5))} stops."
        add = math.ceil(short)
        return f"We need about {add} more {fuel_unit(f.game, add)} to reach the flag, so add that at the stop."

    def strategist_report(self, f):
        S = self.strat
        if f.session != "race":
            if f.laps_done % 2:
                return None
            msg = f"P{f.position} on times." if f.position else ""
            if f.time_left:
                mins = max(1, round(f.time_left / 60))
                msg += f" {'1 minute' if mins == 1 else f'{mins} minutes'} left in {f.session}."
            return msg.strip() or None
        bits = []
        togo = self.laps_to_go(f)
        if f.position:
            if f.laps_done == 1 and self.grid_pos:
                d = self.grid_pos - f.position
                bits.append(f"P{f.position} after lap one" + (f", up {d} from the start." if d > 0 else
                                                               f", down {-d} from the start." if d < 0 else ", holding station."))
            else:
                bits.append(f"P{f.position}" + (f", {_say_laps(math.ceil(togo))} to go." if togo else "."))
        elif togo:
            bits.append(f"{_say_laps(math.ceil(togo))} to go.")
        plan = self.fuel_plan(f)
        if plan:
            bits.append(plan)
        if (f.gap_ahead is not None and f.gap_ahead < 15) or f.car_ahead is not None:
            if f.gap_ahead is None or f.gap_ahead < 15:
                g = S["gaps"]
                trend = ""
                cur_line_gap = g[-1][0] if (g and g[-1][0] is not None) else f.gap_ahead
                if cur_line_gap is not None and len(g) >= 2 and g[-2][0] is not None:
                    rate = g[-2][0] - cur_line_gap
                    trend = (f", you're taking {rate:.1f} a lap" if rate > 0.05 else
                             f", he's pulling {-rate:.1f} a lap" if rate < -0.05 else ", holding steady")
                desc = self._nearest_car_desc(f, "ahead")
                gap_txt = f"{f.gap_ahead:.1f} up the road" if f.gap_ahead is not None else "up the road"
                bits.append(f"Car ahead is {desc}, {gap_txt}{trend}." if desc else f"Car ahead is {gap_txt}{trend}.")
        if (f.gap_behind is not None and f.gap_behind < 2.0) or (f.car_behind is not None and f.gap_behind is None):
            desc = self._nearest_car_desc(f, "behind")
            gap_txt = f"{f.gap_behind:.1f} back" if f.gap_behind is not None else "behind"
            bits.append(f"Car behind is {desc}, {gap_txt}." if desc else f"Car behind is {gap_txt}.")
        return " ".join(bits[:3]) or None

    @staticmethod
    def _fuel_verdict(f, togo, fpl):
        """(plan, words) for the fuel still needed to reach the flag. plan: None (no stop), ("save", litres a lap)
        or ("stop", first lap of the window, last lap of the window)."""
        need = togo * fpl + 0.3 * fpl
        short = need - f.fuel
        if short <= 0:
            return None, "Fuel's good to the flag, no stop needed."
        u = fuel_unit(f.game)
        if f.game in NO_REFUEL_GAMES:
            per = short / max(togo, 1)
            return ("save", per), f"We're {short:.1f} {u} short. Lift and coast, save {per:.2f} a lap to make the flag."
        if short / max(togo, 1) < 0.08 * fpl:
            per = short / max(togo, 1)
            return ("save", per), f"We're {short:.1f} {u} short. Save {per:.2f} a lap and we make it."
        laps_fuel = f.fuel / fpl
        close = f.laps_done + max(1, int(laps_fuel - 0.3))
        open_ = f.laps_done + 1
        stops = 1
        if f.fuel_cap > 0:
            usable = max(f.fuel_cap - 0.5, fpl)
            stops = max(1, math.ceil(short / usable))
            if stops == 1:
                open_ = max(open_, f.laps_done + math.ceil(togo - usable / fpl))
        open_ = min(open_, close)
        win = f"between lap {open_} and lap {close}" if open_ < close else f"on lap {close}"
        if stops > 1:
            return ("stop", open_, close), f"We need {stops} stops for fuel, the first {win}."
        add = math.ceil(short)
        return ("stop", open_, close), f"We need one stop for fuel, {win}. Plan on adding about {add} {fuel_unit(f.game, add)}."

    def fuel_plan(self, f):
        """Race fuel plan: said when first known (and again after a stop), then re-checked every lap. It's said
        again only when the driver has to act on it: the no-stop or fuel-saving plan no longer reaches the flag,
        or the pit window closes earlier because the car is using more than planned."""
        if f.game in RALLY_GAMES:
            return None
        S = self.strat
        togo, fpl = self.laps_to_go(f), self.fuel_per_lap()
        if not fpl or togo is None or f.fuel <= 0:
            return None
        plan, words = self._fuel_verdict(f, togo, fpl)
        if "plan" not in S["said"]:
            S["said"].add("plan")
            S["plan"] = plan
            return words
        old = S["plan"]
        if plan is None:
            if old is not None and old[0] == "save" and f.fuel >= (togo + 0.5) * fpl:
                S["plan"] = None
            return None
        if old is None:
            if plan[0] == "stop" or f.fuel < togo * fpl:
                S["plan"] = plan
                return "Fuel update, we're using more than planned. " + words
            return None
        if old[0] == "save":
            if plan[0] == "stop" or plan[1] > old[1] * 1.5 + 0.03:
                S["plan"] = plan
                return "Fuel update, we're using more than planned. " + words
            return None
        if plan[0] == "stop" and plan[2] < old[2]:
            S["plan"] = ("stop", min(old[1], plan[2]), plan[2])
            return f"Fuel update, we're using more than planned. Box by lap {plan[2]} at the latest."
        return None

    def _wear_pct(self, f):
        if not f.tyre_wear:
            return None
        w = list(f.tyre_wear)
        if f.tyre_wear_frac:
            if self.eng["wear_dir"] is None:
                self.eng["wear_dir"] = "left" if sum(w) / 4 > 0.5 else "worn"
            w = [(1 - x) * 100 if self.eng["wear_dir"] == "left" else x * 100 for x in w]
        return w

    def engineer(self, f, now, line):
        if not self.on("engineer"):
            return
        E = self.eng
        if line and f.fuel > 0 and f.game not in RALLY_GAMES:
            fpl = self.fuel_per_lap()
            togo = self.laps_to_go(f)
            racing = f.session == "race" and self.on("strategist") and togo is not None
            if fpl and not racing and f.session == "race" and f.game in NO_REFUEL_GAMES:
                laps_fuel = f.fuel / fpl
                if togo is not None and laps_fuel < togo - 0.05:
                    if laps_fuel < 1.15 and f"dry{self.stint}" not in E["said"]:
                        E["said"].update((f"dry{self.stint}", f"short{self.stint}"))
                        self.say("engineer", "Fuel's critical. Lift and coast hard or we won't make the flag.", now, True)
                    elif f"short{self.stint}" not in E["said"]:
                        E["said"].add(f"short{self.stint}")
                        self.say("engineer", self.fuel_need(f), now, False)
            elif fpl and not racing:
                laps_fuel = f.fuel / fpl
                for mark, text, urgent in ((1.15, "Box this lap or you'll run dry.", True),
                                           (2.0, "Two laps of fuel left. Box soon.", False),
                                           (3.0, "Fuel for three more laps.", False)):
                    if laps_fuel < mark and f"fuel{mark}{self.stint}" not in E["said"]:
                        E["said"].update(f"fuel{m}{self.stint}" for m in (1.15, 2.0, 3.0) if m >= mark)
                        self.say("engineer", text, now, urgent)
                        break
            elif fpl:
                laps_fuel = f.fuel / fpl
                plan = self.strat.get("plan")
                covered = plan is not None and plan[0] == "stop" and f.laps_done + 1 >= plan[2]
                if laps_fuel < 1.15 and laps_fuel < togo - 0.05 and not covered and f"dry{self.stint}" not in E["said"]:
                    E["said"].add(f"dry{self.stint}")
                    self.say("engineer", "Fuel's critical. Lift and coast hard or we won't make the flag."
                             if f.game in NO_REFUEL_GAMES else "Box this lap or you'll run dry.", now, True)
        if line and f.energy is not None and f.game not in RALLY_GAMES:
            self._energy_calls(f, now)
        if now - self._slow_t >= 0.25 or line:
            self._slow_t = now
            self._wear_check(f, now)
            self._damage(f, now)
            self._temps(f, now)
            self._track_limits(f, now)

    def _energy_calls(self, f, now):
        """Virtual energy (LMU Hypercar / GT3, RaceRoom classes that use it): in those classes it, not the tank, usually
        sets the stint length. Called on the line, like fuel, and only when energy runs out before the fuel does."""
        E = self.eng
        epl = self.energy_per_lap(f)
        if not epl:
            return
        laps_e = f.energy / epl
        fpl = self.fuel_per_lap()
        laps_f = f.fuel / fpl if (fpl and f.fuel > 0) else None
        if f.fuel > 0 and laps_f is None:
            return
        if laps_f is not None and laps_e >= laps_f - 0.3:
            return
        togo = self.laps_to_go(f)
        if togo is not None and laps_e >= togo - 0.05:
            return
        st = self.stint
        if laps_f is not None and laps_e >= 3.0 and f"elimit{st}" not in E["said"]:
            E["said"].add(f"elimit{st}")
            self.say("engineer", f"Energy's the limit this stint, not fuel. About {_laps_left(laps_e)} of energy.", now)
        if f.session == "race" and togo is not None and togo - laps_e < 0.6 and togo <= 8:
            if f"eshort{st}" not in E["said"]:
                E["said"].add(f"eshort{st}")
                self.say("engineer", "We're a touch short on energy to the flag. Lift and coast into the big stops.", now)
            return
        for mark, text, urgent in ((1.15, "Box this lap or you'll run out of energy.", True),
                                   (2.0, "Two laps of energy left. Box soon.", False),
                                   (3.0, "Energy for three more laps.", False)):
            if laps_e < mark and f"energy{mark}{st}" not in E["said"]:
                E["said"].update(f"energy{m}{st}" for m in (1.15, 2.0, 3.0) if m >= mark)
                self.say("engineer", text, now, urgent)
                break

    _TEMP_LIMITS = {"water_temp": (110.0, 10.0, 120.0, 18.0), "oil_temp": (130.0, 12.0, 145.0, 20.0)}

    def _temps_lap(self, f):
        """On the line: the lap's typical temperature becomes this car's normal once three green laps are in."""
        T = self.temps
        for name in self._TEMP_LIMITS:
            xs = T["lap"].pop(name, None)
            if xs and not self.lap_pit:
                hist = T["base"].setdefault(name, [])
                if len(hist) < 3:
                    hist.append(sorted(xs)[len(xs) // 2])

    def _temps(self, f, now):
        if f.in_pit or f.speed < 40:
            return
        T = self.temps
        for name, (hot_abs, hot_rel, crit_abs, crit_rel) in self._TEMP_LIMITS.items():
            v = getattr(f, name, None)
            if v is None:
                continue
            T["lap"].setdefault(name, []).append(v)
            hist = T["base"].get(name) or []
            base = sorted(hist)[len(hist) // 2] if len(hist) >= 3 else None
            hot = max(hot_abs, base + hot_rel) if base is not None else None
            crit = max(crit_abs, base + crit_rel) if base is not None else crit_abs + 5.0
            level = 2 if v >= crit else (1 if hot is not None and v >= hot else 0)
            said = T["said"].get(name, 0)
            if level == 0:
                if said and v < (hot if hot is not None else crit) - 5.0:
                    T["said"][name] = 0
                T["hot_t"].pop(name, None)
                continue
            since = T["hot_t"].setdefault(name, now)
            if level <= said or now - since < 4.0:
                continue
            T["said"][name] = level
            what = "Water temp" if name == "water_temp" else "Oil temp"
            if level == 2:
                self.say("engineer", f"{what}'s critical, {v:.0f} degrees. Get out of the tow and short-shift, or you'll"
                                     " cook the engine.", now, True)
            else:
                self.say("engineer", f"{what}'s climbing, {v:.0f} degrees. Find some clean air.", now)

    def _track_limits(self, f, now):
        """LMU counts track-limits points; each new one is a step closer to a penalty."""
        n = f.track_limits
        if n is None:
            return
        last = self.tl["last"]
        self.tl["last"] = n
        if last is not None and n > last and f.session in ("race", "qualifying") and now - self.tl["t"] > 8.0:
            self.tl["t"] = now
            count = f" That's {n} now." if 1 < n < 50 else ""
            self.say("engineer", f"Track limits strike.{count} Keep it inside the white lines.", now)

    def _wear_check(self, f, now):
        E = self.eng
        wear = self._wear_pct(f)
        if wear:
            worst = max(range(4), key=lambda k: wear[k])
            last = E.get("wear_last")
            if wear[worst] < 10:
                E["wear_mark"] = 0
            elif last is not None and wear[worst] < last - 15:
                E["wear_mark"] = next((m for m in (85, 70, 50) if wear[worst] >= m), 0)
            E["wear_last"] = wear[worst]
            for mark in (85, 70, 50):
                if wear[worst] >= mark > E["wear_mark"]:
                    E["wear_mark"] = mark
                    self.say("engineer", (f"{WHEELS[worst].capitalize()} is nearly gone, {mark} percent worn."
                                          + ("" if f.game in RALLY_GAMES else " Think about a stop."))
                             if mark == 85 else f"{WHEELS[worst].capitalize()} is at {mark} percent wear.", now, urgent=mark == 85)
                    break

    def _damage(self, f, now):
        """Only new or clearly worse damage is called: a first hit, a new part of the car, or about double the
        damage since the last call. Small knocks don't repeat the same message."""
        E = self.eng
        names = ["at the front", "at the rear", "on the left", "on the right", "underneath"]
        if f.damage is not None:
            lvl = f.damage
            if E["dmg"] is None:
                E["dmg"] = lvl if lvl < 0.5 else 0.0
                if lvl < 0.5:
                    return
            elif lvl < E["dmg"] - 0.02:
                E["dmg"], E["heavy"] = lvl, lvl >= 0.5 and E["heavy"]
                return
            base = E["dmg"]
            if lvl >= 0.5 and not E["heavy"]:
                E["dmg"], E["heavy"], E["dmg_t"] = lvl, True, now
                self.say("engineer", "Heavy damage. Nurse the car to the finish." if f.game in RALLY_GAMES
                         else "Heavy damage. Box and get it fixed.", now, urgent=True)
            elif (base < 0.05 <= lvl or lvl >= base + 0.15) and now - E["dmg_t"] > 20:
                first = base < 0.05
                E["dmg"], E["dmg_t"] = lvl, now
                self.say("engineer", "We've picked up some damage. Keep an eye on the balance." if first else
                         "That's more damage. Car's getting worse, take it easy for a lap.", now)
                self.chatter("spotter", "contact", self.facts(f), now, reaction=True)
            return
        if not f.damage_parts:
            return
        parts = [max(0.0, x) for x in f.damage_parts]
        total = sum(parts)
        if E["dmg_parts"] is None or total < (E["dmg"] or 0) - 0.5:
            E["dmg_parts"], E["dmg"], E["dmg_calls"] = list(parts), total, [0] * 5
            if any(x > 1.0 for x in parts):
                E["dmg_calls"] = [1 if x > 1.0 else 0 for x in parts]
            return
        prev = E["dmg_parts"]
        calls = E.setdefault("dmg_calls", [0] * 5)
        new_area = [k for k in range(5) if parts[k] > 1.0 and calls[k] == 0]
        worse = [k for k in range(5) if calls[k] == 1 and parts[k] >= 3 * max(prev[k], 1.0) and parts[k] - prev[k] >= 5]
        if (new_area or worse) and now - E["dmg_t"] > (20 if new_area else 60):
            areas = (new_area or worse)[:2]
            where = " and ".join(names[k] for k in areas)
            self.say("engineer", f"We've picked up some damage {where}. Keep an eye on the balance." if new_area else
                     f"More damage {where}. Take it easy for a lap and see how she feels.", now)
            self.chatter("spotter", "contact", self.facts(f), now, reaction=True)
            for k in areas:
                calls[k] += 1
                prev[k] = parts[k]
            E["dmg"], E["dmg_t"] = total, now

    def strategist(self, f, now, line):
        if f.session != "race" or not self.on("strategist"):
            return
        S = self.strat
        if f.position:
            if S["pos"] is None:
                S["pos"] = f.position
            elif f.position != S["pos"]:
                if S["pos_new"] != f.position:
                    S["pos_new"], S["pos_t"] = f.position, now
                elif now - S["pos_t"] >= 3 and self.moving_since and now - self.moving_since > 20:
                    d = S["pos"] - f.position
                    S["pos"] = f.position
                    if d > 0:
                        ahead_d = self._nearest_car_desc(f, "ahead")
                        extra = f" Next ahead is {ahead_d}" + (f", {f.gap_ahead:.1f} up the road." if f.gap_ahead else ".") if ahead_d else ""
                        self.say("strategist", f"P{f.position}. Up {'a place' if d == 1 else f'{d} places'}.{extra}", now)
                        self.chatter(random.choice(["spotter", "strategist"]), "gain", self.facts(f), now, reaction=True)
                    else:
                        ahead_d = self._nearest_car_desc(f, "ahead")
                        extra = f" {ahead_d} is {f.gap_ahead:.1f} ahead." if (ahead_d and f.gap_ahead) else (f" {ahead_d} is ahead." if ahead_d else "")
                        self.say("strategist", f"P{f.position}, lost {'a place' if d == -1 else f'{-d} places'}.{extra}", now)
                        self.chatter(random.choice(["engineer", "strategist"]), "loss", self.facts(f), now, reaction=True)
            else:
                S["pos_new"] = None
        if not line:
            if 0.55 <= f.pct <= 0.82 and now - S.get("pit_chk_t", 0.0) >= 1.0:
                S["pit_chk_t"] = now
                self._check_pit_opportunity(f, now, f.laps_done + 1)
            return
        lap_no = f.laps_done + 1
        S["gaps"].append((f.gap_ahead, f.gap_behind))
        n_rep = self.every()
        if not n_rep or f.laps_done % n_rep:
            plan = self.fuel_plan(f)
            if plan:
                self.say("strategist", plan, now)
        self._check_pit_opportunity(f, now, lap_no)
        if f.race_laps:
            left = f.race_laps - f.laps_done
            if left == 1:
                self.say("strategist", "Last lap. Bring it home.", now, urgent=True)
                self.chatter("engineer", "last_lap", self.facts(f), now, force=True)
        elif f.time_left is not None:
            lap = self.avg_lap()
            if lap and f.time_left < lap and "last" not in S["said"]:
                S["said"].add("last")
                self.say("strategist", "Clock's about to run out. This should be your last lap.", now, urgent=True)
        if f.gap_behind is not None and len(S["gaps"]) >= 2 and S["gaps"][-2][1] is not None:
            if f.gap_behind < 1.0 and S["gaps"][-2][1] - f.gap_behind > 0.15:
                desc = self._nearest_car_desc(f, "behind")
                who_prefix = f"{desc}, " if desc else ""
                self.say("strategist", f"Car behind is {who_prefix}{f.gap_behind:.1f} back and closing. Watch your mirrors.", now)
        if f.rain is not None and f.game not in RALLY_GAMES:
            soon, later, eventually = f.rain_in_10 or 0.0, f.rain_in_30 or 0.0, f.rain_later or 0.0
            falling = f.precip if f.precip is not None else f.rain
            if falling >= 0.05 or max(soon, later, eventually) < 0.05:
                for k in ("rain_10", "rain_30", "rain_later"):
                    S["said"].discard(k)
            elif soon >= 0.25 and "rain_10" not in S["said"]:
                S["said"].update(("rain_10", "rain_30", "rain_later"))
                heavy = " and it looks heavy, think about wets" if soon >= 0.55 else ""
                self.say("strategist", f"Rain expected in the next ten minutes{heavy}.", now)
            elif later >= 0.25 and "rain_30" not in S["said"]:
                S["said"].update(("rain_30", "rain_later"))
                self.say("strategist", "Weather radar shows rain within half an hour.", now)
            elif eventually >= 0.25 and "rain_later" not in S["said"] and "rain_30" not in S["said"]:
                S["said"].add("rain_later")
                self.say("strategist", "Radar shows rain on the way. No timing yet, I'll call it when it's close.", now)
        if f.rain is not None and f.game not in RALLY_GAMES:
            was = S["rain"]
            S["rain"] = f.rain
            if f.rain >= 0.25:
                S["wet"] = True
            if was is not None:
                togo_r = self.laps_to_go(f)
                enough_laps = togo_r is None or togo_r >= 2.0
                if was < 0.35 <= f.rain and enough_laps and "pit_wet" not in S["said"]:
                    S["said"].add("pit_wet")
                    S["said"].discard("pit_dry")
                    lead = "Rain's here and it's heavy." if was < 0.05 else "It's getting wet out there."
                    self.say("strategist", f"{lead} Good time to make a pit stop this lap for wets.", now, urgent=True)
                elif was < 0.05 <= f.rain:
                    self.say("strategist", "Rain's starting. Careful on the painted lines.", now)
                elif S.get("wet") and was >= 0.05 > f.rain and enough_laps and "pit_dry" not in S["said"]:
                    S["said"].add("pit_dry")
                    S["said"].discard("pit_wet")
                    S["wet"] = False
                    self.say("strategist", "Rain's stopped and the line is drying. Good time to pit for slicks.", now)

    def _check_pit_opportunity(self, f: Frame, now: float, lap_no: int):
        """Proactively advise the driver when it is a good time to make a pit stop based on fuel window,
        traffic undercut/clean air, tyre degradation, pace drop-off, and car damage."""
        if f.game in RALLY_GAMES:
            return
        S = self.strat
        if S["boxed_lap"] is not None and f.laps_done - S["boxed_lap"] < 2:
            return
        togo = self.laps_to_go(f)
        plan = S.get("plan")
        if plan and plan[0] == "stop":
            _, open_, close = plan
            target_lap = (open_ + close) // 2
            win_key = f"window_{self.stint}"
            if lap_no >= close:
                if f"box_{lap_no}" not in S["said"]:
                    S["said"].add(f"box_{lap_no}")
                    self.say("strategist", "Box this lap, box this lap. Last lap of your fuel window.", now, urgent=True)
                return
            if open_ <= lap_no < close:
                if f.gap_ahead is not None and 0.15 < f.gap_ahead < 1.8 and f"undercut_{self.stint}" not in S["said"]:
                    S["said"].add(f"undercut_{self.stint}")
                    S["said"].add(win_key)
                    ahead_desc = self._nearest_car_desc(f, "ahead")
                    who = f" behind {ahead_desc}" if ahead_desc else " in traffic"
                    self.say("strategist",
                             f"Pit window is open and you're losing time{who}. Good time to make a pit stop this lap for the undercut.",
                             now, urgent=True)
                    return
                if lap_no == open_ and win_key not in S["said"]:
                    S["said"].add(win_key)
                    self.say("strategist",
                             f"Pit window's open from this lap through lap {close}. Clean air ahead, stay out a lap or box when ready.",
                             now)
                    return
                if lap_no == target_lap and f"opt_pit_{self.stint}" not in S["said"]:
                    S["said"].add(f"opt_pit_{self.stint}")
                    self.say("strategist",
                             f"Good time to make your pit stop this lap — right in the middle of the window, {_say_laps(close - lap_no + 1)} before you have to box.",
                             now)
                    return
        if togo is None or togo >= 2.0:
            wear = self._wear_pct(f)
            max_wear = max(wear) if wear else 0.0
            pace_drop = (self.lap_times[-1] - self.best_lap) if (len(self.lap_times) >= 2 and self.best_lap) else 0.0
            if max_wear >= 65 and f"pit_tyre_{self.stint}" not in S["said"]:
                S["said"].add(f"pit_tyre_{self.stint}")
                w_idx = max(range(4), key=lambda k: wear[k])
                self.say("strategist",
                         f"{WHEELS[w_idx].capitalize()} tyre is at {max_wear:.0f} percent wear"
                         + (f" and pace is down {tenths(pace_drop)}." if pace_drop > 0.6 else ".")
                         + " Good time to make a pit stop this lap for fresh tyres.",
                         now, urgent=max_wear >= 80)
                return
            if max_wear >= 48 and pace_drop >= 1.2 and f"pit_pace_{self.stint}" not in S["said"]:
                S["said"].add(f"pit_pace_{self.stint}")
                self.say("strategist",
                         f"Lap times have dropped {tenths(pace_drop)} off your best on worn tyres. Good time to pit for fresh rubber.",
                         now)
                return
            dmg_heavy = (f.damage is not None and f.damage >= 0.35) or (
                f.damage_parts and sum(max(0.0, x) for x in f.damage_parts) >= 18.0
            )
            if dmg_heavy and pace_drop >= 1.0 and f"pit_dmg_{self.stint}" not in S["said"]:
                S["said"].add(f"pit_dmg_{self.stint}")
                self.say("strategist",
                         "Damage is costing us lap time. Good time to make a pit stop this lap and get the car repaired.",
                         now, urgent=True)

    def pit_advice(self, f: Frame) -> str:
        """Instant on-demand pit stop recommendation when the driver asks about pitting."""
        if not f:
            return "No telemetry yet to check the pit window."
        if f.game in RALLY_GAMES:
            return "There are no pit stops on a rally stage."
        S = self.strat
        togo = self.laps_to_go(f)
        fpl = self.fuel_per_lap()
        laps_fuel = (f.fuel / fpl) if (fpl and f.fuel > 0) else None
        wear = self._wear_pct(f)
        max_wear = max(wear) if wear else 0.0
        plan = S.get("plan")
        lap_no = f.laps_done + 1
        if plan and plan[0] == "stop" and (S["boxed_lap"] is None or f.laps_done - S["boxed_lap"] >= 2):
            _, open_, close = plan
            if lap_no >= close:
                return f"Box this lap! You're at the end of your fuel window with {laps_fuel:.1f} laps of fuel left." if laps_fuel else "Box this lap! Pit window is closing."
            if open_ <= lap_no < close:
                if f.gap_ahead is not None and f.gap_ahead < 1.8:
                    return f"Yes, good time to pit this lap for the undercut — window is open through lap {close} and you're in traffic."
                return f"Pit window is open now through lap {close}. Good time to box at the end of this lap."
            if lap_no < open_:
                return f"Stay out for now. Your pit window opens on lap {open_} and closes on lap {close}."
        if max_wear >= 65 and (togo is None or togo >= 2.0):
            return f"Yes, tyres are at {max_wear:.0f} percent wear. Good time to box this lap for fresh tyres."
        if (f.damage and f.damage >= 0.35) or self.eng.get("heavy"):
            return "Yes, we have significant damage. Box this lap for repairs."
        epl = self.energy_per_lap(f) if f.energy is not None else None
        laps_e = (f.energy / epl) if epl else None
        if laps_e is not None and (laps_fuel is None or laps_e < laps_fuel - 0.3) and (togo is None or laps_e < togo - 0.05):
            if laps_e < 2.2:
                return f"Yes, box this lap — only {laps_e:.1f} laps of virtual energy left."
            return f"Not this lap, about {_laps_left(laps_e)} of virtual energy left (energy is the limit this stint)."
        if laps_fuel is not None:
            if togo is not None and laps_fuel >= togo + 0.3:
                return f"No stop needed — fuel is good to the flag with {laps_fuel:.1f} laps in the tank and tyres at {max_wear:.0f} percent wear." if wear else f"No stop needed — fuel is good to the flag ({laps_fuel:.1f} laps in the tank)."
            if togo is not None and f.game in NO_REFUEL_GAMES:
                return "No stop for fuel, it won't help. " + self.fuel_need(f)
            if laps_fuel < 2.2:
                if f.game in NO_REFUEL_GAMES:
                    return (f"A stop won't help, there's no refuelling. Lift and coast, "
                            f"only {laps_fuel:.1f} laps of fuel left.")
                return f"Yes, box this lap — only {laps_fuel:.1f} laps of fuel left."
            if togo is not None:
                return f"Not this lap, {laps_fuel:.1f} laps of fuel left. " + self.fuel_need(f)
        if laps_fuel is None and not wear:
            return "Stay out — nothing in the data says you need to stop right now."
        return "Stay out — fuel and tyres look healthy right now."

    def banter(self, f, now):
        if now - self.last_spoken < 50 or f.in_pit or f.speed < 60 or not self.lap_times:
            return
        level = self.chatter_level()
        quiet = 50 if level == "lots" else 90
        if level == "off" or now - self.last_spoken < quiet or now - self.last_chat < quiet or not self.voice.idle(now):
            return
        if now - getattr(self.voice, "busy_until", 0.0) < 15:
            return
        if not self.voice.on_straight.is_set() or (self.spot["left"] or self.spot["right"]):
            return
        roles = [r for r in ("engineer", "strategist", "spotter") if self.on(r)]
        if roles:
            facts = self.facts(f)
            event = "quiet"
            last, best = self.lap_times[-1], min(self.lap_times)
            tg = self.coach.target() if self.coach is not None else None
            if tg:
                facts["pace_pct_of_quick_lap"] = round(100.0 * last / tg[0], 1)
            if (tg and last > tg[0] * 1.03) or last > best * 1.015:
                event = "quiet_slow"
            self.chatter(random.choice(roles), event, facts, now)
            self.last_spoken = now

    CAR_LEN = 4.8

    FLAG_CALLS = {"yellow": "Yellow flag. Careful, no overtaking.",
                  "fcy": "Full course yellow. Slow down and hold your position.",
                  "vsc": "Virtual safety car. Keep to the delta, no overtaking.",
                  "sc": "Safety car, safety car. Hold your position.",
                  "blue": "Blue flag. Faster car behind, let him through."}

    def flags(self, f, now):
        """Race control: a flag is called once it has shown for half a second (no flicker), once per showing;
        the same flag again a moment later isn't repeated. The end of a caution is called too."""
        F = self.flg
        fl = f.flag if (f.flag in self.FLAG_CALLS and (f.flag != "blue" or f.session == "race")) else None
        if fl != F["cur"]:
            F["cur"], F["since"] = fl, now
            return
        if now - F["since"] < 0.5:
            return
        caution = fl in ("fcy", "vsc", "sc")
        if f.in_pit:
            F["said"] = fl
            F["caution"] = fl if caution else None
            return
        role = "engineer" if self.on("engineer") else ("strategist" if self.on("strategist") else None)
        if role is None:
            if fl is None:
                F["said"] = None
            return
        if F.get("caution") and not caution:
            F["caution"] = None
            self.say(role, "Green flag, green flag. Back to racing.", now, urgent=True)
        if fl is None or fl == F["said"]:
            F["said"] = fl
            return
        if now - F["said_t"].get(fl, -1e9) < (30.0 if fl == "blue" else 10.0):
            return
        F["said"] = fl
        F["said_t"][fl] = now
        if caution:
            F["caution"] = fl
        self.say(role, self.FLAG_CALLS[fl], now, urgent=True)

    def spotter(self, f, now):
        P = self.spot
        if f.pos is None or f.others is None or f.in_pit or f.speed < 40 or not self.on("spotter"):
            if P["hist"]:
                P["hist"].clear()
            if P["left"] or P["right"] or P.get("missed"):
                P["left"] = P["right"] = P["missed"] = False
            return
        x, y, z = f.pos
        P["hist"].append((now, x, z))
        while len(P["hist"]) > 2 and now - P["hist"][0][0] > 0.25:
            P["hist"].popleft()
        if f.right is not None:
            rx, rz = f.right
            fx, fz = -rz, rx
            n = math.hypot(fx, fz) or 1.0
            fx, fz = fx / n, fz / n
            rn = math.hypot(rx, rz) or 1.0
            rx, rz = rx / rn, rz / rn
        else:
            t0, x0, z0 = P["hist"][0]
            fx, fz = x - x0, z - z0
            n = math.hypot(fx, fz)
            if n < 0.5:
                return
            fx, fz = fx / n, fz / n
            rx, rz = fz, -fx
        swap = self.cfg.get("spotter_swap") or []
        if swap is True or (isinstance(swap, list) and f.game in swap):
            rx, rz = -rx, -rz
        left = right = False
        was_l_in, was_r_in = P["left"], P["right"]
        reach_busy = self.CAR_LEN + 0.8
        reach_idle = self.CAR_LEN
        for o in f.others:
            dx = o[0] - x
            if dx > 10.0 or dx < -10.0:
                continue
            dz = o[2] - z
            if dz > 10.0 or dz < -10.0 or dx * dx + dz * dz > 100.0:
                continue
            dy = o[1] - y
            if dy > 4.0 or dy < -4.0:
                continue
            lon = dx * fx + dz * fz
            lat = dx * rx + dz * rz
            busy = was_r_in if lat > 0 else was_l_in
            reach = reach_busy if busy else reach_idle
            width = 6.5 if busy else 6.0
            if -reach < lon < reach and 0.8 < abs(lat) < width:
                if lat > 0:
                    right = True
                else:
                    left = True
                if left and right:
                    break
        if P["start"] is None:
            P["start"] = now
        if now - P["start"] < 1.0:
            return
        was_l, was_r = P["left"], P["right"]
        if left:
            P["left_t"] = now
        if right:
            P["right_t"] = now
        new_l = left or (was_l and now - P["left_t"] < 0.4)
        new_r = right or (was_r and now - P["right_t"] < 0.4)
        msg = None
        if new_l and new_r and not (was_l and was_r):
            msg = "Three wide, you're in the middle."
        elif new_l and not was_l and not new_r:
            msg = "Car left."
        elif new_r and not was_r and not new_l:
            msg = "Car right."
        elif was_l and not new_l:
            msg = "Clear all round." if was_r and not new_r else "Clear left."
        elif was_r and not new_r:
            msg = "Clear right."
        if new_l or new_r:
            if not (was_l or was_r):
                P["since"], P["still"] = now, False
            elif not P["still"] and now - (P["since"] or now) > 4.0 and msg is None:
                P["still"] = True
                msg = "Still there."
        P["left"], P["right"] = new_l, new_r
        hold = getattr(self.voice, "hold", None)
        if hold is not None and hold.is_set():
            if msg:
                P["missed"] = True
        elif P.get("missed"):
            P["missed"] = False
            if msg is None and (new_l or new_r):
                msg = ("Three wide, you're in the middle." if new_l and new_r else
                       "Car left." if new_l else "Car right.")
        if msg:
            if msg in ("Car left.", "Car right.") and f.others_meta:
                want_right = (msg == "Car right.")
                best_m, best_d = None, 999.0
                for in_box_only in (True, False):
                    for m in f.others_meta:
                        mp = m.get("pos")
                        if not mp:
                            continue
                        dx, dz = mp[0] - x, mp[2] - z
                        lon = dx * fx + dz * fz
                        lat = dx * rx + dz * rz
                        if (lat > 0) == want_right and (not in_box_only or (-reach_busy < lon < reach_busy and 0.8 < abs(lat) < 6.5)):
                            d_m = math.hypot(dx, dz)
                            if d_m < best_d and d_m <= 25.0:
                                best_d, best_m = d_m, m
                    if best_m is not None:
                        break
                if best_m is not None:
                    side_lbl = "Car right" if want_right else "Car left"
                    parts_s = [side_lbl]
                    if best_m.get("name"):
                        parts_s.append(str(best_m["name"]))
                    if best_m.get("position"):
                        parts_s.append(f"P{best_m['position']}")
                    if best_m.get("car"):
                        parts_s.append(f"in the {best_m['car']}")
                    bd_i = max(1, round(best_d))
                    parts_s.append(f"{bd_i} {'metre' if bd_i == 1 else 'metres'}")
                    msg = ", ".join(parts_s) + "."
            self.voice.say(msg, now, "spot", voice=self.voice_for("spotter"), who="SPOTTER")




def _svg_trace(best, last, corners, w=900, h=220):
    if not best:
        return ""
    vmax = max(max(best["speed"]), max(last["speed"]) if last else 0) or 1

    def path(arr):
        pts = [f"{x * w / BINS:.1f},{h - 20 - arr[x] / vmax * (h - 40):.1f}" for x in range(0, BINS, 4)]
        return "M" + " L".join(pts)
    marks = "".join(f'<line x1="{c[0] * w / BINS:.0f}" y1="10" x2="{c[0] * w / BINS:.0f}" y2="{h - 20}" class="m"/>'
                    f'<text x="{c[0] * w / BINS + 3:.0f}" y="22" class="t">T{i + 1}</text>' for i, c in enumerate(corners))
    lastp = f'<path d="{path(last["speed"])}" class="l"/>' if last else ""
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Speed trace">{marks}'
            f'<path d="{path(best["speed"])}" class="b"/>{lastp}</svg>')


_RE_SAFE_REPORT = re.compile(r"[^A-Za-z0-9_-]+")
_RE_SPOKEN_TIME = re.compile(r"\b(\d+) (\d\d\.\d)\b")
_RE_REPORT_FILE = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})_(.*?)(_after_race\.txt|_setup\.txt|\.html)$")


def write_report(coach, sessions, existing_path=None):
    import html

    def _pct(x, fmt):
        return fmt.format(x) if isinstance(x, (int, float)) else "—"
    os.makedirs(REPORT_DIR, exist_ok=True)
    game, track, car = coach.key
    times = [h["time"] for h in coach.history]
    clean_times = [h["time"] for h in coach.history if not h.get("pit") and not h.get("invalid")]
    ref_times = clean_times or [h["time"] for h in coach.history if not h.get("pit")] or times
    best_t = coach.best_time or min(ref_times)
    tb = coach.theoretical_best()
    rows = []
    for ci, c in enumerate(coach.corners):
        b = coach.best_corner.get(ci, {})
        segs = []
        locks = spins = 0
        for h in coach.history:
            cm = h["corners"].get(ci)
            if cm is not None:
                sg = cm.get("seg")
                if ok(sg) and not h.get("pit"):
                    segs.append(sg)
                if cm.get("lock"):
                    locks += 1
                if cm.get("spin"):
                    spins += 1
        avg_loss = (sum(segs) / len(segs) - b["seg"]) if segs and ok(b.get("seg")) else None
        issues = coach.issue_counts.get(ci, {})
        top = max(issues.items(), key=lambda kv: kv[1])[0] if issues else "—"
        rows.append((ci + 1, avg_loss, stdev(segs), b.get("min_speed", 0), locks, spins, top))
    rows_sorted = sorted(rows, key=lambda r: -(r[1] or 0))
    focus = ", ".join(f"Turn {r[0]}" for r in rows_sorted[:3] if (r[1] or 0) > 0.05) or "consistency"
    trows = "".join(
        f"<tr><td>Turn {r[0]}</td><td>{'' if r[1] is None else f'{r[1]:+.2f}s'}</td><td>{r[2]:.2f}s</td>"
        f"<td>{r[3]:.0f}</td><td>{r[4] or ''}</td><td>{r[5] or ''}</td><td>{html.escape(r[6].replace('k p h', 'km/h'))}</td></tr>" for r in rows)
    lrows_list = []
    for i, h in enumerate(coach.history):
        t = h["time"]
        note = " (pit)" if h.get("pit") else (" (off track)" if h.get("invalid") else "")
        lrows_list.append(f"<tr><td>{i + 1}</td><td>{fmt_time(t).replace(' ', ':')}{note}</td><td>{t - best_t:+.2f}</td></tr>")
    lrows = "".join(lrows_list)
    prog = "".join(f"<tr><td>{html.escape(str(x['date']))}</td><td>{fmt_time(x['best']).replace(' ', ':')}</td>"
                   f"<td>{x['laps']}</td><td>{_pct(x.get('pace_pct'), '{:.1f}%')}</td>"
                   f"<td>{_pct(x.get('consistency'), '±{:.2f}s')}</td></tr>" for x in sessions[-10:])
    svg = _svg_trace(coach.ref, coach.last_filled, coach.corners)
    crew = getattr(coach, "crew", None)
    try:
        measured_fpl = crew.fuel_per_lap() if crew is not None else None
    except Exception:
        measured_fpl = None
    cons = consistency_of(clean_times)
    cons_note = f" · {cons['label']}" if cons else " (σ)"
    tg = coach.target()
    sess_best = min(clean_times) if clean_times else None
    pace = coach.pace_pct(sess_best) if sess_best else None
    pace_kpi = (f'<div class="k"><span>Pace vs target ({fmt_time(tg[0]).replace(" ", ":")}, {html.escape(coach.target_words())})'
                f'</span><b>{pace:.1f}%</b></div>' if pace is not None else "")
    advice = pace_advice(pace, cons)
    verdict = f"<p><strong>Where you are:</strong> {html.escape(advice)}</p>" if advice else ""

    def _sgn(x):
        return "—" if x is None else f"{x:+.2f}s"
    drills = getattr(coach, "drills_done", None) or []
    drills_html = ("<h2>Practice drills</h2><div class=\"wrap\"><table><tr><th>Corner</th><th>Clean laps</th>"
                   "<th>Avg vs your best, before</th><th>Avg vs your best, during</th><th>Best effort</th></tr>"
                   + "".join(f"<tr><td>Turn {d['turn']}</td><td>{d['laps']} of {d['planned']}</td><td>{_sgn(d['before'])}</td>"
                             f"<td>{_sgn(d['avg'])}</td><td>{_sgn(d['best'])}</td></tr>" for d in drills)
                   + "</table></div>") if drills else ""
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coach Report · {html.escape(track)}</title><style>
:root{{--bg:#fafaf7;--fg:#1d1d1b;--mut:#6b6b66;--line:#e3e2dc;--acc:#2f6f9f;--acc2:#c2552d}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ecebe6;--mut:#9a9993;--line:#2c2c2a;--acc:#7fb3d9;--acc2:#e8875f}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,sans-serif;margin:0;padding:24px 16px}}
main{{max-width:960px;margin:auto}} h1{{font-size:24px;margin:0}} .sub{{color:var(--mut)}}
.kpis{{display:flex;flex-wrap:wrap;gap:12px;margin:18px 0}} .k{{border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:140px}}
.k b{{display:block;font-size:22px;font-variant-numeric:tabular-nums}} .k span{{color:var(--mut);font-size:12px}}
table{{border-collapse:collapse;width:100%;margin:8px 0 22px;font-variant-numeric:tabular-nums}} th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}}
th{{color:var(--mut);font-weight:600;font-size:12px}} h2{{font-size:17px;margin:22px 0 4px}}
svg{{width:100%;height:auto;border:1px solid var(--line);border-radius:10px}} .b{{fill:none;stroke:var(--acc);stroke-width:1.6}}
.l{{fill:none;stroke:var(--acc2);stroke-width:1.2;opacity:.85}} .m{{stroke:var(--line)}} .t{{fill:var(--mut);font-size:11px}}
.legend span{{margin-right:14px}} .legend i{{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:4px}}
.wrap{{overflow-x:auto}}</style></head><body><main>
<h1>Coach Report</h1><div class="sub">{html.escape(track)} · {html.escape(car)} · {html.escape(game)} · {html.escape(coach.session_start)}</div>
<div class="kpis"><div class="k"><span>Best lap</span><b>{fmt_time(best_t).replace(' ', ':')}</b></div>
<div class="k"><span>Theoretical best</span><b>{fmt_time(tb).replace(' ', ':') if tb else '—'}</b></div>
<div class="k"><span>Laps</span><b>{len(times)}</b></div>
{pace_kpi}<div class="k"><span>Consistency{cons_note}</span><b>{f"±{cons['sd']:.2f}s" if cons else f"{stdev(ref_times):.2f}s"}</b></div></div>{verdict}
<p><strong>Next focus:</strong> {focus}.</p>{setup_sheet_html(sheet_with_measured_fuel(getattr(coach, "last_setup_sheet", None), measured_fpl, game))}{f'<p><strong>Pre-race setup (Strategist &amp; Coach):</strong> {html.escape(coach.last_setup_briefing["strategist"].replace("k p h", "km/h"))} {html.escape(coach.last_setup_briefing["coach"].replace("k p h", "km/h"))}</p>' if getattr(coach, "last_setup_briefing", None) else ''}
{drills_html}<h2>Speed trace</h2><div class="legend"><span><i style="background:var(--acc)"></i>Best lap</span><span><i style="background:var(--acc2)"></i>Last lap</span></div>{svg}
<h2>Turn by turn</h2><div class="wrap"><table><tr><th>Corner</th><th>Avg loss vs your best</th><th>Variation</th><th>Best min speed (km/h)</th><th>Lock-ups</th><th>Wheelspin</th><th>Most common issue</th></tr>{trows}</table></div>
<h2>Laps</h2><div class="wrap"><table><tr><th>Lap</th><th>Time</th><th>Gap to best</th></tr>{lrows}</table></div>
<h2>Progress</h2><div class="wrap"><table><tr><th>Session</th><th>Best</th><th>Laps</th><th>Pace vs target</th><th>Consistency</th></tr>{prog}</table></div>
</main></body></html>"""
    if existing_path and os.path.dirname(existing_path) == REPORT_DIR:
        path = existing_path
    else:
        stem = _RE_SAFE_REPORT.sub("_", f"{time.strftime('%Y-%m-%d_%H%M')}_{track}_{car}")
        path, k = os.path.join(REPORT_DIR, stem + ".html"), 2
        while os.path.exists(path) or os.path.exists(os.path.splitext(path)[0] + "_after_race.txt"):
            path, k = os.path.join(REPORT_DIR, f"{stem}_{k}.html"), k + 1
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(doc)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        raise
    return path



# The keys are the saved setting (kept for existing configs); the labels describe a coaching style.
COACH_PERSONALITIES = [
    ("Apex — All-round pro, roasts your mistakes", "apex"),
    ("Rotation — Weight transfer, one skill at a time", "almeida"),
    ("Composed — Calm, corner-phase pro (Default)", "mansell"),
    ("Feel — Sensory, traction circle, no coasting", "bentley"),
    ("Exit — GT racer, exit speed & delta", "perel"),
    ("Data — Surgical telemetry engineer", "naujoks"),
]
_PERSONALITY_NAMES = [n for n, _ in COACH_PERSONALITIES]
_PERSONALITY_BY_LABEL = dict(COACH_PERSONALITIES)
_LABEL_BY_PERSONALITY = {v: n for n, v in COACH_PERSONALITIES}

COACH_PERSONA_PROMPTS = {
    "apex": (
        "You are 'Apex', an elite sim racing performance coach talking to {name} over team radio. "
        "Your coaching blends the core schools of modern driver coaching: "
        "weight transfer and trail braking to rotate the car, light hands to feel front grip, and isolating ONE skill at a time; "
        "breaking corners into entry, mid-corner minimum speed and exit phases with eyes up; "
        "focusing on where braking ends rather than where it starts, trading steering for throttle around the traction circle, and zero dead coasting; "
        "giving up a little entry speed for a straighter exit and earlier full throttle; "
        "and checking the driver's seat-of-the-pants feel against hard telemetry facts. "
        "PERSONALITY TWIST: When {name} drives cleanly or asks a technical or setup question, you are razor-sharp, composed, and constructive. "
        "HOWEVER, when the telemetry shows {name} making mistakes (locking tyres, wheelspin, pedal overlap, braking 30+ metres early, coasting mid-corner, "
        "sawing at the wheel, or running off track), you get JUST A BIT UNHINGED — roast the mistake with colorful, passionate exasperation "
        "(e.g. 'stop stabbing the pedal like you're trying to kill a spider', 'my grandmother brakes deeper than that', 'hero entry, zero exit') "
        "before immediately giving the exact biomechanical fix."
    ),
    "almeida": (
        "You are 'Rotation', a sim racing coach talking to {name} over team radio. "
        "You are direct, analytical, myth-busting ('your seat-of-the-pants feel can lie to you', 'lap time is an output, not a goal'), and slightly "
        "unhinged when {name} stabs the pedals or overdrives. Focus on weight transfer, trail braking to rotate the car up to its maximum rotation "
        "point, light hands to feel front grip, and isolating ONE fundamental skill at a time."
    ),
    "mansell": (
        "You are 'Composed', a pro driver and coach talking to {name} over team radio. "
        "You are calm, methodical, reassuring, and authoritative. Break every corner into distinct phases (braking, turn-in, mid-corner minimum speed, exit), "
        "emphasising vision ('eyes up through the apex'), progressive brake bleed-off, and keeping the car platform settled."
    ),
    "bentley": (
        "You are 'Feel', a veteran motorsport coach talking to {name} over team radio. "
        "You are warm, encouraging, and sensory-focused. Emphasise where braking ends (the release point) rather than just where it starts, "
        "the traction circle ('unwind the steering wheel as you squeeze the throttle'), eliminating dead coasting, and staying relaxed."
    ),
    "perel": (
        "You are 'Exit', a professional GT endurance driver and coach talking to {name} over team radio. "
        "You are pragmatic, race-hardened, and delta-focused. Prioritise sacrificing a fraction of entry speed to straighten the exit and hit 100% throttle "
        "earlier for the next straight, while managing tyre temperatures and pressures."
    ),
    "naujoks": (
        "You are 'Data', a clinical esports team manager and telemetry specialist talking to {name} over team radio. "
        "You are surgical, no-nonsense, and data-driven. Connect exact telemetry figures (metres, km/h, tenths) to the driver's seat-of-the-pants feel, "
        "corner geometry, and decisive inputs without mid-corner hesitation."
    ),
}

SYSTEM_PROMPT = """{persona}
Rules:
- Two short sentences maximum, usually one. No lists, no markdown, no emojis.
- Base answers on the session data provided. Corners are numbered in the order found on the lap (Turn 1, Turn 2...).
- If data is missing, say so briefly. Never invent lap times.
- Use metres, km/h and tenths of a second. Say numbers the way a person would say them out loud.
- Translate raw telemetry into what the car's weight transfer, rotation, and tyres are doing, and give ONE clear action to drill.
- If the status says no sim is running, you're in the garage before or between sessions: answer radio checks,
  general driving, technique and setup questions in character, and never make up session data."""


def build_system_prompt(cfg):
    name = cfg.get("driver_name") or "the driver"
    p_key = cfg.get("coach_personality", DEFAULT_CONFIG["coach_personality"])
    persona = COACH_PERSONA_PROMPTS.get(p_key, COACH_PERSONA_PROMPTS["apex"]).format(name=name)
    return SYSTEM_PROMPT.format(persona=persona, name=name)




SETUP_AREAS = ("Fuel", "Strategy", "Tyres", "Brakes", "Aero", "Suspension", "Differential", "Electronics", "Other")


def _json_reply(raw):
    """A JSON object from a model reply: the whole reply, a fenced block, or the {...} inside some prose."""
    if not raw:
        return None
    j = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE).strip()
    for cand in (j, j[j.find("{"):j.rfind("}") + 1] if "{" in j else ""):
        if cand.startswith("{") and cand.endswith("}"):
            try:
                d = json.loads(cand)
            except Exception:
                continue
            if isinstance(d, dict):
                return d
    return None


_AREA_MAP = {"Tire": "Tyres", "Tires": "Tyres", "Tyre": "Tyres", "Brake": "Brakes", "Braking": "Brakes",
             "Diff": "Differential", "Drivetrain": "Differential", "Chassis": "Suspension", "Damper": "Suspension",
             "Dampers": "Suspension", "Springs": "Suspension", "Arb": "Suspension", "Wings": "Aero",
             "Downforce": "Aero", "Tc": "Electronics", "Abs": "Electronics", "Tc/Abs": "Electronics"}


def parse_setup_sheet(raw):
    """The written setup list ([(area, setting, change)]) from a JSON reply, or None."""
    d = _json_reply(raw)
    rows = d.get("sheet") if isinstance(d, dict) else None
    if not isinstance(rows, list):
        return None
    out = []
    for r in rows[:20]:
        if not isinstance(r, dict):
            continue
        setting, change = r.get("setting"), r.get("change")
        if isinstance(change, bool) or not isinstance(change, (str, int, float)) or not str(change).strip():
            continue
        area = str(r.get("area") or "Other").strip().title()
        area = _AREA_MAP.get(area, area)
        out.append((area if area in SETUP_AREAS else "Other", str(setting or "").strip()[:60], str(change).strip()[:120]))
    return out or None


# --- AI providers (OpenAI, Google Gemini, DeepSeek) -----------------------------------------------------------
# Gemini and DeepSeek both serve OpenAI-compatible chat endpoints, so one client library covers all three.
AI_PROVIDERS = OrderedDict((
    ("openai", {"name": "OpenAI", "label": "OpenAI (GPT)", "base_url": None, "env": "OPENAI_API_KEY",
                "models": OPENAI_MODELS, "key_url": "https://platform.openai.com/api-keys",
                "tokens": "max_completion_tokens", "extra": {}}),
    ("gemini", {"name": "Gemini", "label": "Google Gemini", "env": "GEMINI_API_KEY",
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "models": GEMINI_MODELS, "key_url": "https://aistudio.google.com/apikey",
                # Short radio replies: keep thinking light so answers come back fast.
                "tokens": "max_tokens", "extra": {"reasoning_effort": "low"}}),
    ("deepseek", {"name": "DeepSeek", "label": "DeepSeek", "base_url": "https://api.deepseek.com",
                  "env": "DEEPSEEK_API_KEY", "models": DEEPSEEK_MODELS,
                  "key_url": "https://platform.deepseek.com/api_keys", "tokens": "max_tokens", "extra": {}}),
))
_AI_LABELS = [p["label"] for p in AI_PROVIDERS.values()]
_AI_BY_LABEL = {p["label"]: k for k, p in AI_PROVIDERS.items()}

_OPENAI_CLIENTS = {}
_OPENAI_LOCK = threading.Lock()


class OpenAIReplyError(RuntimeError):
    """The AI answered, but with nothing usable (empty, cut off, refused or filtered). The message is speakable."""


def ai_provider(cfg):
    p = (cfg or {}).get("ai_provider") or "openai"
    return p if p in AI_PROVIDERS else "openai"


def ai_key(cfg, provider=None):
    p = provider or ai_provider(cfg)
    return ((cfg or {}).get(f"{p}_api_key") or os.environ.get(AI_PROVIDERS[p]["env"])
            or DEFAULT_CONFIG.get(f"{p}_api_key") or "").strip()


def ai_model(cfg, provider=None):
    p = provider or ai_provider(cfg)
    return ((cfg or {}).get(f"{p}_model") or DEFAULT_CONFIG[f"{p}_model"]).strip()


def ai_label(cfg, provider=None):
    """'Gemini gemini-3.5-flash': who answers, for the radio screen and setup sheets."""
    p = provider or ai_provider(cfg)
    return f"{AI_PROVIDERS[p]['name']} {ai_model(cfg, p)}"


def openai_client(key, base_url=None):
    """One client per (API key, endpoint), reused (each new client opens its own connection pool)."""
    import openai
    key = (key or "").strip()
    if not key:
        raise ValueError("no API key")
    with _OPENAI_LOCK:
        c = _OPENAI_CLIENTS.get((key, base_url))
        if c is None:
            c = _OPENAI_CLIENTS[(key, base_url)] = openai.OpenAI(api_key=key, base_url=base_url, timeout=20.0,
                                                                 max_retries=1)
        return c


_RE_UNSUPPORTED_MCT = re.compile(
    r"(?:unsupported|unknown|unrecognized)\s+(?:parameter|request argument)[^:]*:\s*['\"]?max_completion_tokens\b"
    r"|['\"]?max_completion_tokens['\"]?\s+(?:is\s+)?not\s+supported", re.IGNORECASE)


def _mct_unsupported(exc):
    """True only when the model rejects the max_completion_tokens parameter itself (older models want max_tokens),
    not for any other bad request that merely mentions it (a bad value, a context-length error...)."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        if err.get("param") == "max_completion_tokens" and err.get("code") in ("unsupported_parameter", "unknown_parameter"):
            return True
        text = str(err.get("message") or exc)
    else:
        text = str(exc)
    return bool(_RE_UNSUPPORTED_MCT.search(text))


def openai_chat(key, model, messages, max_tokens=300, timeout=20.0, provider="openai"):
    """Chat completion text from any provider in AI_PROVIDERS. max_completion_tokens counts a reasoning model's
    thinking too, so a small budget can come back empty or cut off: that is retried once with a bigger budget,
    then raised as OpenAIReplyError (never returned as '' or as half a sentence to be spoken)."""
    import openai
    spec = AI_PROVIDERS.get(provider) or AI_PROVIDERS["openai"]
    name = spec["name"]
    client = openai_client(key, spec["base_url"]).with_options(timeout=timeout)
    kw = {"model": model, "messages": messages}
    extra = dict(spec["extra"])
    param = [spec["tokens"]]

    def request(budget):
        while True:
            try:
                # Provider-specific options go in the JSON body, so an older openai package never rejects them.
                return client.chat.completions.create(**kw, **{param[0]: budget}, **({"extra_body": extra} if extra else {}))
            except openai.BadRequestError as e:
                if param[0] == "max_completion_tokens" and _mct_unsupported(e):
                    param[0] = "max_tokens"
                    continue
                # An optional tuning parameter this model doesn't take: drop it and ask again.
                bad = next((k for k in extra if re.search(rf"\b{re.escape(k)}\b", str(e))), None)
                if bad is None:
                    raise
                extra.pop(bad)

    budgets = (max_tokens, max(1024, max_tokens * 4))
    for attempt, budget in enumerate(budgets):
        r = request(budget)
        if not r.choices:
            raise OpenAIReplyError(f"{name} sent back nothing. Try again.")
        choice = r.choices[0]
        msg = choice.message
        if getattr(msg, "refusal", None):
            raise OpenAIReplyError(f"{name} declined to answer that one.")
        if choice.finish_reason == "content_filter":
            raise OpenAIReplyError(f"{name} filtered that answer. Try asking it another way.")
        text = (msg.content or "").strip()
        cut = choice.finish_reason == "length"
        if text and not cut:
            return text
        if attempt == 0:
            continue
        raise OpenAIReplyError(f"{name} ran out of room for an answer. Try a shorter question or another model."
                               if cut else f"{name} sent an empty answer. Try again.")


def _ai_transient(e):
    """A failure worth retrying on another provider: network, timeout, rate limit or a server-side error."""
    try:
        import openai
    except Exception:
        return False
    return isinstance(e, (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError))


def ai_chat_ex(cfg, messages, max_tokens=300, timeout=20.0):
    """(reply, 'Provider model') from the chosen provider. With 'ai_fallback' on, a network, rate-limit or
    server failure moves on to the other providers that have a key, so the radio keeps working. A failure
    carries .ai_provider (the provider that failed last) so the spoken explanation names the right one."""
    primary = ai_provider(cfg)
    order = [primary]
    if cfg.get("ai_fallback", True):
        order += [p for p in AI_PROVIDERS if p != primary and ai_key(cfg, p)]
    for i, p in enumerate(order):
        try:
            return openai_chat(ai_key(cfg, p), ai_model(cfg, p), messages, max_tokens=max_tokens,
                               timeout=timeout, provider=p), ai_label(cfg, p)
        except Exception as e:
            try:
                e.ai_provider = p
            except Exception:
                pass
            if i == len(order) - 1 or not _ai_transient(e):
                raise


def ai_chat(cfg, messages, max_tokens=300, timeout=20.0):
    return ai_chat_ex(cfg, messages, max_tokens, timeout)[0]


def openai_problem(e, provider="openai"):
    """A short spoken explanation of an AI failure (the key test strips ' Check it in Settings.')."""
    if isinstance(e, OpenAIReplyError):
        return str(e)
    provider = getattr(e, "ai_provider", None) or provider
    name = (AI_PROVIDERS.get(provider) or AI_PROVIDERS["openai"])["name"]
    msg = str(e).lower()
    if isinstance(e, ValueError) and "api key" in msg:
        return f"There's no {name} API key. Check it in Settings."
    try:
        import openai
    except Exception:
        return "The OpenAI package isn't installed. Run the setup again."
    if isinstance(e, openai.AuthenticationError):
        return f"{name} didn't accept the API key. Check it in Settings."
    if isinstance(e, openai.PermissionDeniedError):
        return f"{name} refused access for this key. Check the key and model in Settings."
    if isinstance(e, openai.NotFoundError):
        return f"{name} couldn't find that model. Check it in Settings."
    if isinstance(e, openai.RateLimitError):
        if "quota" in msg or "billing" in msg or "balance" in msg:
            return f"The {name} account is out of credit. Top it up, then try again."
        return f"{name} is rate limiting us. Give it a few seconds."
    if isinstance(e, openai.APIStatusError) and getattr(e, "status_code", None) == 402:
        return f"The {name} account is out of credit. Top it up, then try again."
    if isinstance(e, openai.APIConnectionError):
        return f"Can't reach {name} right now. Check the internet connection."
    if isinstance(e, openai.BadRequestError):
        if provider == "gemini" and "api key" in msg:
            return f"{name} didn't accept the API key. Check it in Settings."
        return f"{name} rejected the request. Check the model in Settings."
    return f"The radio link to {name} dropped. Try again in a moment."


_RE_SETUP_LABEL = re.compile(
    r"^\s*(?:(?:\d+[.)]|[-•*])\s*)?(?:\*\*|__)?(?P<role>strategist|coach|apex)(?:\*\*|__)?\s*[:\-—](?:\*\*|__)?\s*(?P<text>.*)$",
    re.IGNORECASE)


def parse_setup_dialogue(raw, fallback_strat, fallback_coach):
    """(strategist line, coach line) from a setup reply: the JSON object asked for, else 'Strategist: ...' /
    'Coach: ...' lines (markdown bullets and bold labels allowed). A part that can't be found keeps its fallback
    (the caller checks for that)."""
    strat, coach = fallback_strat, fallback_coach
    raw = raw or ""
    d = _json_reply(raw)
    if isinstance(d, dict):
        s, c = d.get("strategist"), d.get("coach")
        if isinstance(s, str) and s.strip():
            strat = s.strip()
        if isinstance(c, str) and c.strip():
            coach = c.strip()
        return strat, coach
    cur = None
    parts = {"s": [], "c": []}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _RE_SETUP_LABEL.match(line)
        if m:
            cur = "s" if m.group("role").lower() == "strategist" else "c"
            line = m.group("text").strip()
        if cur and line:
            parts[cur].append(line)
    if parts["s"]:
        strat = " ".join(parts["s"]).strip() or strat
    if parts["c"]:
        coach = " ".join(parts["c"]).strip() or coach
    return strat, coach


def _radio_steps(text):
    """A radio call split into the steps it asks for (when GPT gave no written list)."""
    steps = []
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        for part in re.split(r",\s+(?:and\s+)?|\s+and\s+(?=(?:set|shift|move|run|drop|bump|soften|stiffen|raise|lower|"
                             r"open|close|trim|add|take|go|keep|pack|load|fill|target|bleed|start)\b)", sent):
            part = part.strip(" .!?")
            if len(part.split()) >= 2 and _RE_SETUP_WORD.search(part) and not re.match(r"(?i)(coach|copy|setup's|trust)\b", part):
                steps.append(part[:1].upper() + part[1:])
    return steps[:12]


_RE_SETUP_WORD = re.compile(r"(?i)\b(wing|bias|pressures?|psi|bar|fuel|litres?|liters?|kilos?|kg|anti-roll|arb|preload|diff\w*|"
                            r"tc|abs|traction|rake|ride height|damp\w*|bump|rebound|toe|camber|ducts?|compound|wets|slicks|"
                            r"stops?|stint|springs?|gear\w*|downforce|splitter|brake|engine map|map|clicks?|mm|millimetres?)\b")


def sheet_with_measured_fuel(sheet, fpl, game):
    """The setup sheet with its 'Use per lap' row replaced by the fuel actually used, once laps have measured it
    (the sheet is made at the start of a session, when that's still a guess)."""
    if not sheet or not fpl:
        return sheet
    out = dict(sheet)
    out["items"] = [(a, st, f"{fpl:.1f} {fuel_unit(game)} (measured this session)" if (a, st) == ("Fuel", "Use per lap") else ch)
                    for a, st, ch in (sheet.get("items") or [])]
    return out


def setup_sheet_html(sheet):
    """The setup sheet as a table for the HTML report ("" when there's none)."""
    rows = (sheet or {}).get("items") or []
    if not rows:
        return ""
    import html as _h
    applied = set((sheet or {}).get("applied") or ())
    body = "".join(
        f"<tr><td>{_h.escape(a)}</td><td>{_h.escape(st)}</td><td>{_h.escape(ch)}</td>"
        f"<td>{'Applied ✓' if idx in applied else '—'}</td></tr>"
        for idx, (a, st, ch) in enumerate(rows)
    )
    return (f"<h2>Race setup sheet</h2><p>{_h.escape(sheet.get('source', ''))}, {_h.escape(sheet.get('made', ''))}</p>"
            f"<div class=\"wrap\"><table><tr><th>Area</th><th>Setting</th><th>Change</th><th>In Sim</th></tr>{body}</table></div>")


def _crew_said(who, line):
    """'Strategist: ...' (not 'Strategist: Strategist pre-race setup ...')."""
    line = (line or "").replace("k p h", "km/h")
    return line if line.lower().startswith(who.lower()) else f"{who}: {line}"


def setup_sheet_text(sheet):
    """The setup sheet as plain text (saved next to the reports, and what Copy puts on the clipboard)."""
    head = " · ".join(x for x in (sheet.get("race"), sheet.get("conditions"), sheet.get("grid")) if x)
    lines = [f"SimCoach race setup: {sheet.get('title', '')} ({sheet.get('sim', '')}), {sheet.get('made', '')}", head, ""]
    applied = set(sheet.get("applied") or ())
    by_area = OrderedDict()
    for idx, (area, setting, change) in enumerate(sheet.get("items") or []):
        by_area.setdefault(area, []).append((idx, setting, change))
    for area, rows in by_area.items():
        lines.append(area.upper())
        for idx, setting, change in rows:
            mark = "[x]" if idx in applied else "[ ]"
            lines.append(f"  {mark} {setting}: {change}" if setting else f"  {mark} {change}")
        lines.append("")
    if sheet.get("sim_setup_path"):
        lines += [f"SIM SETUP FILE: {sheet['sim_setup_path']}", ""]
    lines += ["WHAT THE CREW SAID", f"  {_crew_said('Strategist', sheet.get('strategist', ''))}",
              f"  {_crew_said('Coach', sheet.get('coach', ''))}", "", f"({sheet.get('source', '')})"]
    return "\n".join(lines).replace("k p h", "km/h") + "\n"


CSP_SETUP_MMF = "Local\\SimCoach.CSPSetup.v1"


class SetupApplier:
    r"""Parses setup sheet items and applies (or reverts) them directly in the sim when a box is clicked:
    - Writes/updates native garage setup files (.ini for AC, .json for ACC, .svm for LMU/rFactor 2, and
      structured setup profiles in Documents\SimCoach Reports\Setups).
    - Pushes live setup values to Assetto Corsa CSP shared memory (Local\SimCoach.CSPSetup.v1) when available.
    - Updates the active Coach / SimReader setup state so live telemetry and tests reflect every clicked box."""

    BASELINE = {
        "fuel_load": 20.0,
        "fuel_per_lap": 2.4,
        "pit_stops": 0,
        "tyre_compound": "slick",
        "press_psi": [26.8, 26.8, 26.8, 26.8],
        "brake_bias_pct": 56.0,
        "brake_ducts": [3, 3],
        "rear_wing": 6,
        "ride_height_mm": [55.0, 55.0, 70.0, 70.0],
        "arb_front": 4,
        "arb_rear": 4,
        "dampers_front": 6,
        "dampers_rear": 6,
        "diff_preload": 60,
        "tc": 3,
        "abs": 3,
    }
    _csp_map = None
    _csp_seq = 0
    _IO_LOCK = threading.Lock()
    _WORD_NUMS = (("one", "1"), ("two", "2"), ("three", "3"), ("four", "4"))

    @classmethod
    def _scope(cls, s_low: str, c_low: str, both_name: str = "both") -> str:
        if "both" in c_low or "all four" in c_low or ("front" in s_low and "rear" in s_low):
            return both_name
        if "front" in s_low:
            return "front"
        if "rear" in s_low:
            return "rear"
        c_clean = re.sub(r"than\s+the\s+(?:front|rear)s?", "", c_low)
        pf, pr = c_clean.find("front"), c_clean.find("rear")
        if pf >= 0 and (pr < 0 or pf < pr):
            return "front"
        if pr >= 0 and (pf < 0 or pr < pf):
            return "rear"
        return both_name

    @classmethod
    def parse_item(cls, area: str, setting: str, change: str) -> dict:
        a_low, s_low, c_low = (area or "").lower(), (setting or "").lower(), (change or "").lower()
        for w_str, d_str in cls._WORD_NUMS:
            c_low = re.sub(rf"\b{w_str}\b", d_str, c_low)
        text = f"{a_low} {s_low} {c_low}"
        if "per lap" in s_low or "use per lap" in s_low or ("per lap" in c_low and "fuel" in text):
            m = re.search(r"(\d+(?:\.\d+)?)", c_low)
            v = float(m.group(1)) if m else 2.4
            return {"key": "fuel_per_lap", "op": "set", "val": v, "badge": f"{v:.1f}/lap ✓"}
        if a_low == "fuel" or "fuel" in s_low or ("fuel" in c_low and "save" not in c_low) or re.search(r"\b\d+(?:\.\d+)?\s*(?:litres?|liters?|kilos?)\b", c_low):
            if "reserve" in c_low and not re.search(r"\d+\s*(?:litre|liter|kilo|kg)", c_low):
                return {"key": "fuel_load", "op": "delta", "val": 4.0, "badge": "+1.5 laps ✓"}
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:litres?|liters?|kilos?|kg|l\b)", c_low) or re.search(r"(\d+(?:\.\d+)?)", c_low)
            v = float(m.group(1)) if m else 20.0
            u = "kg" if ("kilo" in c_low or "kg" in c_low) else "L"
            return {"key": "fuel_load", "op": "set", "val": v, "badge": f"{v:g} {u} ✓"}
        if a_low == "strategy" or "plan" in s_low or "stop" in s_low or re.search(r"\b(?:no|\d+)[- ]stop\b", c_low):
            if "no stop" in c_low or "no-stop" in c_low or "no refuel" in c_low or "0-stop" in c_low:
                return {"key": "pit_stops", "op": "set", "val": 0, "badge": "0 stops ✓"}
            m = re.search(r"(\d+)[- ]stop", c_low)
            if m:
                n_st = int(m.group(1))
                return {"key": "pit_stops", "op": "set", "val": n_st, "badge": f"{n_st} stop{'s' if n_st != 1 else ''} ✓"}
            return {"key": "pit_stops", "op": "set", "val": 0, "badge": "Strategy ✓"}
        if "compound" in s_low or ((a_low == "tyres" or "slick" in c_low or "wet" in c_low) and "psi" not in c_low and "pressure" not in text and "click" not in c_low and "bias" not in text):
            lead = c_low.split("(")[0]
            if ("wet" in lead or "rain" in lead or "inter" in lead) and "slick" not in lead:
                return {"key": "tyre_compound", "op": "set", "val": "wet", "badge": "Wets ✓"}
            if "medium" in lead:
                return {"key": "tyre_compound", "op": "set", "val": "medium", "badge": "Med slick ✓"}
            if "hard" in lead:
                return {"key": "tyre_compound", "op": "set", "val": "hard", "badge": "Hard slick ✓"}
            return {"key": "tyre_compound", "op": "set", "val": "slick", "badge": "Slicks ✓"}
        if "pressure" in text or "psi" in c_low:
            scope = cls._scope(s_low, c_low, both_name="all")
            m_d = re.search(r"([+-]\s*\d+(?:\.\d+)?)\s*psi", c_low)
            if m_d:
                d = float(m_d.group(1).replace(" ", ""))
                return {"key": f"press_{scope}", "op": "delta", "val": d, "badge": f"{d:+.1f} PSI ✓"}
            m_up = re.search(r"(?:up|raise|add|bump)\s+(?:by\s+)?(\d+(?:\.\d+)?)\s*psi", c_low)
            if m_up:
                d = float(m_up.group(1))
                return {"key": f"press_{scope}", "op": "delta", "val": d, "badge": f"{d:+.1f} PSI ✓"}
            m_dn = re.search(r"(?:down|drop|bleed|lower)\s+(?:by\s+)?(\d+(?:\.\d+)?)\s*psi", c_low)
            if m_dn:
                d = -float(m_dn.group(1))
                return {"key": f"press_{scope}", "op": "delta", "val": d, "badge": f"{d:+.1f} PSI ✓"}
            m_rng = re.search(r"(\d{2}(?:\.\d+)?)\s*(?:to|-|–)\s*(\d{2}(?:\.\d+)?)\s*psi", c_low)
            if m_rng:
                v = round((float(m_rng.group(1)) + float(m_rng.group(2))) / 2.0, 1)
                return {"key": f"press_{scope}", "op": "set", "val": v, "badge": f"{v:.1f} PSI ✓"}
            m_one = re.search(r"(\d{2}(?:\.\d+)?)\s*psi", c_low)
            v = float(m_one.group(1)) if m_one else 27.2
            return {"key": f"press_{scope}", "op": "set", "val": v, "badge": f"{v:.1f} PSI ✓"}
        if "duct" in text:
            m = re.search(r"([+-]?\d+)\s*click", c_low)
            d = int(m.group(1)) if m else (1 if "open" in c_low else (-1 if "close" in c_low else 0))
            if "close" in c_low and d > 0:
                d = -d
            return {"key": "brake_ducts", "op": "delta", "val": d, "badge": f"Ducts {d:+d} ✓" if d else "Ducts bal ✓"}
        if "bias" in text or a_low == "brakes":
            m = re.search(r"([+-]?\s*\d+(?:\.\d+)?)\s*(?:%|percent)", c_low) or re.search(r"([+-]?\d+(?:\.\d+)?)", c_low)
            v = float(m.group(1).replace(" ", "")) if m else 0.5
            if "rear" in c_low:
                d = -abs(v)
            elif "forward" in c_low or "front" in c_low:
                d = abs(v)
            else:
                d = v
            if abs(d) < 20.0:
                return {"key": "brake_bias_pct", "op": "delta", "val": d, "badge": f"Bias {d:+.1f}% ✓"}
            return {"key": "brake_bias_pct", "op": "set", "val": abs(d), "badge": f"Bias {abs(d):.1f}% ✓"}
        if a_low == "aero" or "wing" in text or "downforce" in text or "splitter" in text:
            m = re.search(r"([+-]?\d+)(?:\s*to\s*[+-]?\d+)?\s*(?:extra\s+)?click", c_low)
            if m:
                d = int(m.group(1))
                if ("trim" in c_low or "lower" in c_low or "less" in c_low or "drop" in c_low) and d > 0:
                    d = -d
            elif "high" in c_low or "more" in c_low or "add" in c_low or "crank" in c_low:
                d = 1
            elif "low" in c_low or "trim" in c_low or "less" in c_low:
                d = -1
            else:
                d = 0
            return {"key": "rear_wing", "op": "delta", "val": d, "badge": f"Wing {d:+d} ✓" if d else "Wing base ✓"}
        if "rake" in text or "ride height" in text:
            m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(?:mm|millimetre)", c_low)
            d = float(m.group(1)) if m else (-1.0 if ("lower" in c_low or "less" in c_low) else 1.0)
            return {"key": "rake_mm", "op": "delta", "val": d, "badge": f"Rake {d:+.0f}mm ✓"}
        if "damper" in text or "bump" in s_low or "rebound" in s_low:
            scope = cls._scope(s_low, c_low, both_name="both")
            m = re.search(r"([+-]?\d+)\s*click", c_low)
            n = abs(int(m.group(1))) if m else 1
            d = -n if "soft" in c_low else (n if ("stiff" in c_low or "firm" in c_low) else n)
            return {"key": f"dampers_{scope}", "op": "delta", "val": d, "badge": f"Damp {d:+d} ✓"}
        if "anti-roll" in text or "arb" in text or a_low == "suspension":
            scope = cls._scope(s_low, c_low, both_name="both")
            m = re.search(r"([+-]?\d+)\s*click", c_low)
            n = abs(int(m.group(1))) if m else 1
            d = -n if "soft" in c_low else (n if "stiff" in c_low else -n)
            return {"key": f"arb_{scope}", "op": "delta", "val": d, "badge": f"ARB {d:+d} ✓"}
        if a_low == "differential" or "preload" in text or "diff" in text:
            m = re.search(r"([+-]?\d+)", c_low)
            if m:
                d = int(m.group(1))
                if ("lower" in c_low or "drop" in c_low or "less" in c_low) and d > 0:
                    d = -d
            elif "lower" in c_low or "drop" in c_low or "less" in c_low:
                d = -1
            elif "higher" in c_low or "raise" in c_low or "more" in c_low:
                d = 1
            else:
                d = 0
            return {"key": "diff_preload", "op": "delta", "val": d, "badge": f"Diff {d:+d} ✓" if d else "Diff prog ✓"}
        if a_low == "electronics" or "tc" in text or "abs" in text or "traction" in text:
            m = re.search(r"([+-]?\d+)\s*click", c_low) or re.search(r"([+-]?\d+)", c_low)
            n = int(m.group(1)) if m else 1
            d = -abs(n) if ("down" in c_low or "lower" in c_low or "off" in c_low) else (abs(n) if ("up" in c_low or "raise" in c_low) else n)
            has_tc = "tc" in s_low or "traction" in s_low or "both" in c_low or "tc" in c_low
            has_abs = "abs" in s_low or "both" in c_low or "abs" in c_low
            k = "tc_abs" if (has_tc and has_abs) else ("abs" if has_abs else "tc")
            return {"key": k, "op": "delta", "val": d, "badge": f"{k.upper().replace('_', '/')} {d:+d} ✓"}
        return {"key": "custom", "op": "set", "val": change, "badge": "Applied ✓"}

    _PREVIEW = (("fuel_load", "Fuel", "{:g} L"), ("pit_stops", "Pit stops", "{}"), ("tyre_compound", "Tyres", "{}"),
                ("press_psi", "Pressures FL/FR/RL/RR", "{} psi"), ("brake_bias_pct", "Brake bias", "{:g}%"),
                ("brake_ducts", "Brake ducts F/R", "{}"), ("rear_wing", "Rear wing", "{}"),
                ("ride_height_mm", "Ride height FL/FR/RL/RR", "{} mm"), ("arb_front", "Front anti-roll bar", "{}"),
                ("arb_rear", "Rear anti-roll bar", "{}"), ("dampers_front", "Front dampers", "{}"),
                ("dampers_rear", "Rear dampers", "{}"), ("diff_preload", "Diff preload", "{} Nm"),
                ("tc", "Traction control", "{}"), ("abs", "ABS", "{}"), ("fuel_per_lap", "Fuel per lap", "{:g} L"))

    @classmethod
    def preview(cls, sheet: dict, applied_after) -> list:
        """What ticking exactly `applied_after` would change, against what's applied now: [(label, before, after)]."""
        before, _ = cls.compute_state(sheet)
        after, _ = cls.compute_state(dict(sheet, applied=sorted(set(applied_after))))
        out = []
        for key, label, fmt in cls._PREVIEW:
            b, a = before.get(key), after.get(key)
            if b == a:
                continue
            def show(x):
                if not isinstance(x, list):
                    return fmt.format(x)
                vals = [f"{y:g}" if isinstance(y, float) else str(y) for y in x]
                return fmt.format(vals[0] if len(set(vals)) == 1 else "/".join(vals))
            same = isinstance(a, list) and isinstance(b, list) and len(set(map(str, a))) == 1 and len(set(map(str, b))) == 1
            out.append((label.split(" FL/")[0].split(" F/R")[0] if same else label, show(b), show(a)))
        return out

    @classmethod
    def compute_state(cls, sheet: dict) -> tuple[dict, dict]:
        """Return (resolved_state, badges_by_idx) for the currently ticked indices in sheet['applied']."""
        st = {
            "fuel_load": cls.BASELINE["fuel_load"],
            "fuel_per_lap": cls.BASELINE["fuel_per_lap"],
            "pit_stops": cls.BASELINE["pit_stops"],
            "tyre_compound": cls.BASELINE["tyre_compound"],
            "press_psi": list(cls.BASELINE["press_psi"]),
            "brake_bias_pct": cls.BASELINE["brake_bias_pct"],
            "brake_ducts": list(cls.BASELINE["brake_ducts"]),
            "rear_wing": cls.BASELINE["rear_wing"],
            "ride_height_mm": list(cls.BASELINE["ride_height_mm"]),
            "arb_front": cls.BASELINE["arb_front"],
            "arb_rear": cls.BASELINE["arb_rear"],
            "dampers_front": cls.BASELINE["dampers_front"],
            "dampers_rear": cls.BASELINE["dampers_rear"],
            "diff_preload": cls.BASELINE["diff_preload"],
            "tc": cls.BASELINE["tc"],
            "abs": cls.BASELINE["abs"],
        }
        applied = set(sheet.get("applied") or ())
        badges = {}
        for idx, (area, setting, change) in enumerate(sheet.get("items") or []):
            act = cls.parse_item(area, setting, change)
            badges[idx] = act["badge"]
            if idx not in applied:
                continue
            k, op, v = act["key"], act["op"], act["val"]
            if k == "fuel_load":
                st["fuel_load"] = round(max(1.0, (st["fuel_load"] + v) if op == "delta" else float(v)), 1)
            elif k == "fuel_per_lap":
                st["fuel_per_lap"] = round(float(v), 2)
            elif k == "pit_stops":
                st["pit_stops"] = max(0, int(v))
            elif k == "tyre_compound":
                st["tyre_compound"] = str(v)
            elif k in ("press_all", "press_front", "press_rear"):
                indices = (0, 1, 2, 3) if k == "press_all" else ((0, 1) if k == "press_front" else (2, 3))
                for i_w in indices:
                    st["press_psi"][i_w] = round((st["press_psi"][i_w] + v) if op == "delta" else float(v), 1)
            elif k == "brake_bias_pct":
                st["brake_bias_pct"] = round(max(40.0, min(75.0, (st["brake_bias_pct"] + v) if op == "delta" else float(v))), 1)
            elif k == "brake_ducts":
                st["brake_ducts"] = [max(0, min(6, x + int(v))) for x in st["brake_ducts"]]
            elif k == "rear_wing":
                st["rear_wing"] = max(0, st["rear_wing"] + int(v))
            elif k == "rake_mm":
                st["ride_height_mm"][2] = round(st["ride_height_mm"][2] + float(v), 1)
                st["ride_height_mm"][3] = round(st["ride_height_mm"][3] + float(v), 1)
            elif k in ("arb_front", "arb_rear", "arb_both"):
                if k in ("arb_front", "arb_both"):
                    st["arb_front"] = max(0, st["arb_front"] + int(v))
                if k in ("arb_rear", "arb_both"):
                    st["arb_rear"] = max(0, st["arb_rear"] + int(v))
            elif k in ("dampers_front", "dampers_rear", "dampers_both"):
                if k in ("dampers_front", "dampers_both"):
                    st["dampers_front"] = max(0, st["dampers_front"] + int(v))
                if k in ("dampers_rear", "dampers_both"):
                    st["dampers_rear"] = max(0, st["dampers_rear"] + int(v))
            elif k == "diff_preload":
                st["diff_preload"] = max(0, st["diff_preload"] + int(v) * 10)
            elif k in ("tc", "abs", "tc_abs"):
                if k in ("tc", "tc_abs"):
                    st["tc"] = max(0, st["tc"] + int(v))
                if k in ("abs", "tc_abs"):
                    st["abs"] = max(0, st["abs"] + int(v))
        return st, badges

    @staticmethod
    def _format_ac_ini(st: dict) -> str:
        comp_idx = 1 if st["tyre_compound"] == "wet" else (1 if st["tyre_compound"] == "medium" else (2 if st["tyre_compound"] == "hard" else 0))
        p = st["press_psi"]
        rh = st["ride_height_mm"]
        df, dr = st.get("dampers_front", 6), st.get("dampers_rear", 6)
        sections = [
            ("FUEL", round(st["fuel_load"])),
            ("TYRES", comp_idx),
            ("PRESSURE_LF", round(p[0])), ("PRESSURE_RF", round(p[1])),
            ("PRESSURE_LR", round(p[2])), ("PRESSURE_RR", round(p[3])),
            ("FRONT_BIAS", round(st["brake_bias_pct"])),
            ("BRAKE_POWER_MULT", 100),
            ("WING_1", st["rear_wing"]), ("WING_2", st["rear_wing"]),
            ("ARB_FRONT", st["arb_front"]), ("ARB_REAR", st["arb_rear"]),
            ("DAMP_BUMP_LF", df), ("DAMP_BUMP_RF", df), ("DAMP_BUMP_LR", dr), ("DAMP_BUMP_RR", dr),
            ("ROD_LENGTH_LF", round(rh[0])), ("ROD_LENGTH_RF", round(rh[1])),
            ("ROD_LENGTH_LR", round(rh[2])), ("ROD_LENGTH_RR", round(rh[3])),
            ("DIFF_PRELOAD", st["diff_preload"]),
            ("TRACTION_CONTROL", st["tc"]), ("ABS", st["abs"]),
        ]
        return "\n".join(f"[{name}]\nVALUE={val}\n" for name, val in sections)

    @staticmethod
    def _format_acc_json(st: dict, car: str = "") -> str:
        comp = 1 if st["tyre_compound"] == "wet" else 0
        p_clicks = [max(0, round((x - 20.0) * 10)) for x in st["press_psi"]]
        bias_clicks = max(0, round((st["brake_bias_pct"] - 50.0) * 5))
        df, dr = st.get("dampers_front", 6), st.get("dampers_rear", 6)
        doc = {
            "carName": car or "gt3",
            "basicSetup": {
                "tyres": {"tyreCompound": comp, "tyrePressure": p_clicks},
                "alignment": {"camber": [0, 0, 0, 0], "toe": [10, 10, 10, 10], "staticCamber": [-3.5, -3.5, -3.0, -3.0], "toeOutLinear": [0, 0, 0, 0], "casterLF": 30, "casterRF": 30, "steerRatio": 14},
                "electronics": {"tC1": st["tc"], "tC2": st["tc"], "aBS": st["abs"], "eCUMap": 0, "fuelMix": 0, "telemetryLaps": 0},
                "strategy": {"fuel": round(st["fuel_load"]), "nPitStops": st["pit_stops"], "tyreSet": 1, "frontBrakePadCompound": 1, "rearBrakePadCompound": 1, "pitStrategy": [], "fuelPerLap": st["fuel_per_lap"]},
            },
            "advancedSetup": {
                "mechanicalBalance": {"aRBFront": st["arb_front"], "aRBRear": st["arb_rear"], "wheelRate": [1, 1, 1, 1], "bumpStopRateUp": [5, 5, 5, 5], "bumpStopRateDn": [5, 5, 5, 5], "bumpStopWindow": [10, 10, 15, 15], "brakeTorque": 20, "brakeBias": bias_clicks},
                "dampers": {"bumpSlow": [df, df, dr, dr], "bumpFast": [4, 4, 4, 4], "reboundSlow": [df + 1, df + 1, dr + 1, dr + 1], "reboundFast": [5, 5, 5, 5]},
                "aeroBalance": {"rideHeight": [round(x) for x in st["ride_height_mm"]], "rodLength": [0, 0, 0, 0], "splitter": 0, "rearWing": st["rear_wing"], "brakeDuct": list(st["brake_ducts"])},
                "drivetrain": {"preload": max(0, st["diff_preload"] // 10)},
            },
            "trackBopType": 0,
        }
        return json.dumps(doc, indent=2) + "\n"

    @staticmethod
    def _format_rf2_svm(st: dict, car: str = "") -> str:
        comp = 1 if st["tyre_compound"] == "wet" else 0
        rear_bias = round(100.0 - st["brake_bias_pct"], 1)
        p_kpa = [round(x / 0.145038) for x in st["press_psi"]]
        rh = st["ride_height_mm"]
        return (
            f'//[[gMa1.002f (c)2026    ]] [[            ]]\n[HEADER]\nVehicleClassSetting="{car}"\n\n'
            f"[GENERAL]\nSymmetric=1\nFuelSetting={round(st['fuel_load'])}\nNumPitstopsSetting={st['pit_stops']}\n\n"
            f"[CONTROLS]\nRearBrakeSetting={rear_bias}\nBrakePressureSetting=100\nTractionControlSetting={st['tc']}\nAntilockBrakesSetting={st['abs']}\n\n"
            f"[REARWING]\nRWSetting={st['rear_wing']}\n\n[BODYAERO]\nBrakeDuctSetting={st['brake_ducts'][0]}\n\n"
            f"[SUSPENSION]\nFrontAntiSwaySetting={st['arb_front']}\nRearAntiSwaySetting={st['arb_rear']}\n\n"
            f"[DRIVELINE]\nDiffPreloadSetting={st['diff_preload']}\n\n"
            f"[FRONTLEFT]\nCompoundSetting={comp}\nPressureSetting={p_kpa[0]}\nRideHeightSetting={round(rh[0])}\n\n"
            f"[FRONTRIGHT]\nCompoundSetting={comp}\nPressureSetting={p_kpa[1]}\nRideHeightSetting={round(rh[1])}\n\n"
            f"[REARLEFT]\nCompoundSetting={comp}\nPressureSetting={p_kpa[2]}\nRideHeightSetting={round(rh[2])}\n\n"
            f"[REARRIGHT]\nCompoundSetting={comp}\nPressureSetting={p_kpa[3]}\nRideHeightSetting={round(rh[3])}\n"
        )

    @classmethod
    def _push_csp_mmf(cls, st: dict):
        if sys.platform != "win32" or ctypes is None:
            return False
        try:
            if cls._csp_map is None:
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                k32.CreateFileMappingW.restype = wintypes.HANDLE
                k32.CreateFileMappingW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR]
                k32.MapViewOfFile.restype = ctypes.c_void_p
                k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
                h = k32.CreateFileMappingW(wintypes.HANDLE(-1), None, 0x04, 0, 64, CSP_SETUP_MMF)
                if h:
                    p = k32.MapViewOfFile(h, 0x0002, 0, 0, 64)
                    if p:
                        cls._csp_map = (h, p)
            if cls._csp_map is None:
                return False
            _, ptr = cls._csp_map
            cls._csp_seq += 1
            odd = cls._csp_seq | 1
            even = odd + 1
            cls._csp_seq = even
            comp = 1 if st["tyre_compound"] == "wet" else 0
            pr = st["press_psi"]
            # Same layout as the Lua reader: version, seq, fuel, tyreCompound, 4 pressures, brakeBias, wing,
            # arbFront, arbRear, tc, abs.
            payload = struct.pack("<iififffffiiiii", 1, odd, float(st["fuel_load"]), comp,
                                  float(pr[0]), float(pr[1]), float(pr[2]), float(pr[3]), float(st["brake_bias_pct"]),
                                  int(st["rear_wing"]), int(st["arb_front"]), int(st["arb_rear"]),
                                  int(st["tc"]), int(st["abs"]))
            ctypes.memmove(ptr, payload, len(payload))
            ctypes.memmove(ptr + 4, struct.pack("<i", even), 4)
            return True
        except Exception:
            return False

    @classmethod
    def _sim_setup_targets(cls, sim: str, track: str, car: str, st: dict) -> list[tuple[str, str]]:
        safe_sim = _RE_SAFE_REPORT.sub("_", sim or "Sim").strip("_")
        safe_trk = _RE_SAFE_REPORT.sub("_", track or "Track").strip("_")
        safe_car = _RE_SAFE_REPORT.sub("_", car or "Car").strip("_")
        setups_dir = os.path.join(REPORT_DIR, "Setups")
        docs = _documents_dir()
        targets = []
        if sim == "ACC":
            content = cls._format_acc_json(st, safe_car)
            targets.append((os.path.join(setups_dir, f"{safe_sim}_{safe_trk}_{safe_car}_SimCoach_Race.json"), content))
            acc_root = os.path.join(docs, "Assetto Corsa Competizione", "Setups")
            if os.path.isdir(acc_root):
                targets.append((os.path.join(acc_root, safe_car, safe_trk, "SimCoach_Race.json"), content))
        elif sim in ("LMU", "rFactor 2"):
            content = cls._format_rf2_svm(st, safe_car)
            targets.append((os.path.join(setups_dir, f"{safe_sim}_{safe_trk}_{safe_car}_SimCoach_Race.svm"), content))
            sub = "Le Mans Ultimate" if sim == "LMU" else "rFactor2"
            rf_root = os.path.join(docs, sub, "UserData", "player", "Settings")
            if os.path.isdir(rf_root):
                targets.append((os.path.join(rf_root, safe_trk, "SimCoach_Race.svm"), content))
        elif sim in ("AC", "AC Rally", "AC EVO"):
            content = cls._format_ac_ini(st)
            targets.append((os.path.join(setups_dir, f"{safe_sim}_{safe_trk}_{safe_car}_SimCoach_Race.ini"), content))
            ac_root = os.path.join(docs, "Assetto Corsa", "setups")
            if os.path.isdir(ac_root):
                targets.append((os.path.join(ac_root, safe_car, safe_trk, "SimCoach_Race.ini"), content))
        else:
            content = json.dumps({"sim": sim, "track": track, "car": car, "setup": st}, indent=2) + "\n"
            targets.append((os.path.join(setups_dir, f"{safe_sim}_{safe_trk}_{safe_car}_SimCoach_Race.json"), content))
        return targets

    @classmethod
    def sync(cls, sheet: dict, coach=None, log=file_log, last_idx: Optional[int] = None) -> dict:
        if not sheet:
            return {"status": "", "badges": {}, "state": {}}
        items = sheet.get("items") or []
        applied = {i for i in (sheet.get("applied") or ()) if isinstance(i, int) and 0 <= i < len(items)}
        sheet["applied"] = applied
        st, badges = cls.compute_state(sheet)
        sheet["applied_state"] = st
        coach = coach or sheet.get("coach_ref")
        sim = sheet.get("sim") or (coach.key[0] if (coach and coach.key) else "Sim")
        raw_title = sheet.get("title") or ""
        parts = [p.strip() for p in raw_title.split("·")]
        track = (coach.key[1] if (coach and coach.key) else (parts[0] if parts else "Track"))
        car = (coach.key[2] if (coach and coach.key) else (parts[1] if len(parts) > 1 else "Car"))
        saved_path = None
        with cls._IO_LOCK:
            for dst, content in cls._sim_setup_targets(sim, track, car, st):
                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    tmp = dst + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as fh:
                        fh.write(content)
                    os.replace(tmp, dst)
                    if saved_path is None:
                        saved_path = dst
                except OSError:
                    pass
            if saved_path:
                sheet["sim_setup_path"] = saved_path
            if sheet.get("path"):
                try:
                    tmp_p = sheet["path"] + ".tmp"
                    with open(tmp_p, "w", encoding="utf-8") as fh:
                        fh.write(setup_sheet_text(sheet))
                    os.replace(tmp_p, sheet["path"])
                except OSError:
                    pass
        if sim == "AC":
            cls._push_csp_mmf(st)
        if coach is not None:
            coach.applied_setup = dict(st)
            lf = coach.last_frame
            if lf is not None and "fuel_load" in st and len(applied) > 0:
                reader = getattr(coach, "_active_reader", None)
                if reader is not None and getattr(reader, "name", "") == "TEST":
                    reader.fuel = float(st["fuel_load"])
                    reader.press = list(st["press_psi"])
        status_msg = ""
        if last_idx is not None and 0 <= last_idx < len(items):
            area, setting, change = items[last_idx]
            lbl_name = setting or area
            act = cls.parse_item(area, setting, change)
            if last_idx in applied:
                status_msg = f"Applied in {sim}: {lbl_name} ({act['badge'].replace(' ✓', '')})"
            else:
                status_msg = f"Reverted in {sim}: {lbl_name}"
            if log:
                log(f"Setup sheet: {status_msg}")
        elif applied:
            status_msg = f"Applied all {len(applied)} changes in {sim}"
            if log:
                log(f"Setup sheet: {status_msg}")
        else:
            status_msg = f"Reverted setup to baseline in {sim}"
        return {"status": status_msg, "badges": badges, "state": st, "setup_file": saved_path}

    @classmethod
    def toggle_item(cls, sheet: dict, idx: int, enabled: Optional[bool] = None, coach=None, log=file_log) -> dict:
        applied = set(sheet.get("applied") or ())
        if enabled is None:
            enabled = idx not in applied
        if enabled:
            applied.add(idx)
        else:
            applied.discard(idx)
        sheet["applied"] = applied
        return cls.sync(sheet, coach=coach, log=log, last_idx=idx)

    @classmethod
    def apply_all(cls, sheet: dict, enabled: bool = True, coach=None, log=file_log) -> dict:
        items = sheet.get("items") or []
        sheet["applied"] = set(range(len(items))) if enabled else set()
        return cls.sync(sheet, coach=coach, log=log, last_idx=None)


# ── Natural-language Q&A ────────────────────────────────────────────────────
class Conversation:
    def __init__(self, cfg, coach: Coach, voice: Voice, overlay, log=print):
        self.cfg, self.coach, self.voice, self.overlay, self.log = cfg, coach, voice, overlay, log
        self.history = []
        self._lock = threading.Lock()

    def handle(self, text):
        self.overlay.post(heard=f"You: {text}")
        now = time.monotonic()
        if not self.coach.live():
            self.voice.on_straight.set()
        key = ai_key(self.cfg)
        tl = text.lower()
        if (self._RE_SETUP.search(tl) and key and not self._RE_SHEET.search(tl)
                and not self._RE_SHEET_CLOSE.search(tl) and not self._RE_SETUP_APPLY.search(tl)):
            threading.Thread(target=self._ask_openai_setup, args=(text,), daemon=True, name="openai-setup").start()
            return
        reply = self.local(text.lower())
        if reply is not None:
            if reply:
                self.voice.say(reply, now, "answer")
                self.overlay.post(tip=reply, rc_t=now, rc_reply=reply, rc_ai="Instant command (no AI call)")
            return
        threading.Thread(target=self._ask_openai, args=(text,), daemon=True, name="openai-chat").start()

    _PERSONAS = [(words, key, desc,
                  re.compile(rf"\b(?:{'|'.join(words)})\s+(?:coach|style|mode|personality)\b"),
                  re.compile(rf"\b(?:to|the)\s+(?:{'|'.join(words)})\b"))
                 for words, key, desc in (
        (("apex", "unhinged"), "apex", "Apex, the all-round pro who roasts your mistakes"),
        (("rotation",), "almeida", "Rotation, weight transfer and one skill at a time"),
        (("composed", "calm"), "mansell", "Composed, calm corner-phase coaching"),
        (("feel", "sensory"), "bentley", "Feel, sensory and traction circle coaching"),
        (("exit",), "perel", "Exit, exit speed and delta coaching"),
        (("data", "telemetry"), "naujoks", "Data, surgical telemetry coaching"))]
    _RE_PERSONA_SWITCH = re.compile(r"\b(?:switch|change|set|use|go)\b")
    _RE_PERSONA_WORD = re.compile(r"\b(?:coach|personality|style|mode)\b")
    _RE_RADIO = re.compile(r"\b(radio check|comms? check|mic check|can you hear me|do you (copy|read( me)?)|how do you read)\b")
    _RE_REPEAT = re.compile(r"\b(repeat|say (that|it) again|what was that|come again)\b")
    _RE_QUIET = re.compile(r"^(please )?(be quiet|go quiet|quiet( please)?|shut up|stop talking|radio silence|mute( coach)?)$")
    _RE_CHATTY = re.compile(r"\b(talk more|more feedback|more coaching|be chatty)\b")
    _RE_NORMAL = re.compile(r"\b(talk less|less feedback|normal coaching|unmute|radio on|back on)\b")
    _RE_LAST_LAP = re.compile(r"\b(last lap|lap time)\b")
    _RE_BEST_LAP = re.compile(r"\bbest (lap|time)\b")
    _RE_CAPTURE = re.compile(
        r"^((ok|okay|right|coach|please),? )*(can you |could you )?(please )?"
        r"(start (a |the )?((game |sim )?(data |telemetry ))?capture|start capturing( (the |some )?(game |sim )?(data|telemetry))?|"
        r"capture( (the |some )?(game |sim )?(data|telemetry))?|"
        r"(start )?record(ing)? (the |some )?(game |sim )?(data|telemetry))"
        r"( for (?P<n>\d+|a|an|one|two|three|four|five|ten|thirty|ninety) (?P<u>seconds?|minutes?))?(,? please|,? now)?$")
    _RE_CAPTURE_STOP = re.compile(r"^((ok|okay|right|coach|please),? )*(please )?(stop|end|finish|cancel) (the )?((game |sim )?(data |telemetry ))?"
                                  r"(capture|capturing|recording)( now|,? please)?$")
    _CAP_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "thirty": 30,
                  "ninety": 90}
    _RE_RESET_REF = re.compile(r"^((ok|okay|right|coach|please),? )*(can you |could you )?(please )?"
                               r"((reset|clear|delete) (the |my |this )?reference|(start |set )?(a )?new reference)"
                               r"(,? please|,? now)?$")
    _RE_BRAKE_TONES = re.compile(r"\b(brake|braking) (markers|callouts|tones|beeps)\b")
    _RE_OFF = re.compile(r"\b(off|stop|no)\b")
    _RE_ALL = re.compile(r"\b(all|every)\b")
    _RE_SPLITS = re.compile(r"\b(split|sector) (deltas?|times|callouts)\b")
    _RE_QUESTION = re.compile(r"^(?!(?:what|how) about\b)(?!(?:will|would|can|could) you\b)"
                              r"(should|shall|are|is|do|does|did|was|were|why|what|what's|whats|how|how's|when|"
                              r"which|who|will|would|can i|could i)\b|\bwhether\b|^tell me if\b")
    _RE_LAST_LAP_ONLY = re.compile(r"(?<!not )(?<!not my )\blast lap\b")
    _RE_REPORT = re.compile(r"\b(write (the |a )?report|session report|debrief me|open (the )?report)\b")
    _RE_THEO = re.compile(r"\b(theoretical|optimal|ultimate) (best|lap)\b")
    _RE_TARGET = re.compile(r"\b(target( lap| time)?|off the pace|how far off|pace percent(age)?|benchmark)\b")
    _RE_CONSISTENCY = re.compile(r"\b(consisten\w*|how (steady|repeatable))\b")
    _RE_PACE = re.compile(r"\b(what('s| is) my pace|how('s| is) (my|the) pace|my average( lap)?|average lap( time)?)\b")
    _RE_FUEL_NEED = re.compile(r"\b(how much fuel (do (i|we) need|to add|should (i|we) add|to (the )?(end|finish|flag))|"
                               r"fuel (to add|to (the )?(end|finish|flag)|needed))\b")
    _RE_FUEL = re.compile(r"\b(how much fuel|fuel (left|level|check)|how's the fuel)\b")
    _RE_ENERGY = re.compile(r"\b(how much (virtual )?energy|(virtual )?energy (left|level|check)|how's the (virtual )?energy|"
                            r"virtual energy)\b")
    _RE_TEMPS = re.compile(r"\b(engine|water|oil) (temps?|temperatures?)\b|\bhow('s| is) the engine\b")
    _RE_TYRES = re.compile(r"\b(how are (my |the )?(tyres|tires)|(tyres?|tires?) (temps?|temperatures?|pressures?|wear|"
                           r"check|status)|(tyre|tire) report)\b")
    _RE_DAMAGE = re.compile(r"\b(damage (check|report|status)|any damage|is the car (ok|okay|damaged)|"
                            r"how bad is the damage)\b")
    _RE_NEAREST = re.compile(r"\b(nearest cars?|cars? around( me)?|who('s| is) (ahead|in front|behind)|car (ahead|in front|behind))\b")
    _RE_PIT = re.compile(r"\b(should i (pit|box)|when (to|should i) (pit|box)|pit (window|stop|strategy|now)|good time to (make a )?pit( stop)?|box this lap)\b")
    _RE_DEBRIEF = re.compile(r"\b(after[- ]?race (report|debrief)|race debrief|full debrief)\b")
    _RE_SHEET = re.compile(r"\b(setup sheet|written setup|(show|open|bring up|display|see)( me)? (the |my )?"
                           r"(race |car |written )?setup)\b")
    _RE_SHEET_CLOSE = re.compile(r"\b(close|hide|dismiss|get rid of)( the| my)? (race |written )?setup( sheet)?\b")
    _RE_SETUP_APPLY = re.compile(r"\b(apply|load|set|put on)( all)?( the| my| this)? (race |pre[- ]?race |car |written )?setup( sheet)?\b")
    _RE_SETUP = re.compile(r"\b((optimal|race|pre[- ]?race|car|suggest( a)?) setup|setup (advice|for the race|recommendation|suggestion)|what setup)\b")

    def _clean_best(self):
        """The best lap that counts: the reference lap (unless it's a provisional off-track one), else this
        session's fastest clean lap; None if there's no clean lap yet."""
        c = self.coach
        if c.best_time and not getattr(c, "ref_provisional", False):
            return c.best_time
        return min((x["time"] for x in c.history if not x.get("pit") and not x.get("invalid")), default=None)

    def _energy_answer(self, fr):
        if fr.energy is None:
            return None
        crew = self.coach.crew
        epl = crew.energy_per_lap(fr) if crew is not None else fr.energy_lap
        laps = f", about {_laps_left(fr.energy / epl)}" if epl else ""
        return f"Virtual energy {fr.energy * 100:.0f} percent{laps}."

    _NUM_WORDS = {w: i for i, w in enumerate(("zero one two three four five six seven eight nine ten eleven twelve "
                                              "thirteen fourteen fifteen sixteen seventeen eighteen nineteen "
                                              "twenty").split())}
    _NUM_WORDS.update({"won": 1, "to": 2, "too": 2, "for": 4, "tree": 3, "ate": 8})
    _RE_DRILL = re.compile(r"\b(?:work on|practi[cs]e|drill|focus on)\s+(?:turn|corner|t)\s*([a-z0-9]+)"
                           r"(?:\s+(?:for\s+)?(?:the\s+next\s+)?([a-z0-9]+)\s+laps?)?")
    _RE_BRIEF_SKIP = re.compile(r"\b(?:skip|stop|cancel|cut|enough of)\s+(?:the\s+|that\s+|this\s+)?(?:setup\s+)?briefing\b")
    _RE_BRIEF_FULL = re.compile(r"\b(?:full|whole|complete)\s+(?:setup\s+)?briefing\b|\b(?:repeat|replay)\s+the\s+(?:setup\s+)?briefing\b")
    _RE_DRILL_STOP = re.compile(r"\b(?:stop|end|cancel|finish|quit)\s+(?:the\s+|this\s+|my\s+)?(?:drill|practice drill)\b")

    def _num(self, w):
        if w is None:
            return None
        return int(w) if w.isdigit() else self._NUM_WORDS.get(w)

    def local(self, t):
        """Instant commands. Anything that changes settings or data must be a short, explicit command,
        so questions like "should I reset my brake bias?" go to the engineer instead."""
        c = self.coach
        hist = c.history
        t = t.strip().lower().rstrip(".!?")
        if len(t.split()) > 10:
            return None
        if self._RE_BRIEF_SKIP.search(t):
            b = c.last_setup_briefing or {}
            n = self.voice.cancel([b.get("strategist"), b.get("coach")] + list(getattr(c.crew, "_short_lines", ())))
            return "Copy, skipping it. The sheet's on the setup button." if n else "Nothing to skip."
        if self._RE_BRIEF_FULL.search(t):
            if c.last_frame is None:
                return "Get in the car first, then ask for the briefing."
            # asked for, so it's answered straight away (priority, like the session-start briefing)
            threading.Thread(target=c.collaborate_race_setup, args=(c.last_frame, time.monotonic()),
                             kwargs={"speak": True, "session_start": True}, daemon=True, name="full-briefing").start()
            return ""
        if self._RE_DRILL_STOP.search(t):
            return c.stop_drill()
        m_dr = self._RE_DRILL.search(t)
        if m_dr and self._num(m_dr.group(1)):
            return c.start_drill(self._num(m_dr.group(1)) - 1, self._num(m_dr.group(2)) or 5)
        if self._RE_RADIO.search(t):
            return f"Loud and clear, {self.cfg.get('driver_name') or 'driver'}."
        if self._RE_SHEET_CLOSE.search(t):
            self.overlay.post(setup_close=True)
            return "Setup sheet closed."
        if self._RE_SETUP_APPLY.search(t):
            if not c.last_setup_sheet:
                c.collaborate_race_setup(c.last_frame, time.monotonic(), speak=False, use_openai=False, show=False)
            if c.last_setup_sheet:
                sheet = c.last_setup_sheet
                changes = SetupApplier.preview(sheet, range(len(sheet.get("items") or [])))
                SetupApplier.apply_all(sheet, enabled=True, coach=c, log=self.log)
                self.overlay.post(setup_sheet=sheet, setup_popup=not (c.last_frame and c.live() and c.last_frame.speed > 3))
                if not changes:
                    return "Setup's already applied, nothing to change."
                said = ", ".join(f"{lbl.split(' FL/')[0].lower()} {a}" for lbl, _b, a in changes[:3])
                said = said.replace(" L", " litres").replace("%", " percent").replace(" Nm", " newton metres")
                more = f", and {len(changes) - 3} more on the sheet" if len(changes) > 3 else ""
                return f"Applied {len(changes)} setup change{'s' if len(changes) != 1 else ''}: {said}{more}."
        if self._RE_SHEET.search(t) and c.last_setup_sheet:
            c._sheet_wait = None
            self.overlay.post(setup_sheet=c.last_setup_sheet, setup_popup=True)
            return "Setup sheet's on your screen."
        if self._RE_REPEAT.search(t):
            return self.voice.last_text or "Nothing to repeat yet."
        if self._RE_QUIET.search(t):
            self.cfg["talk_level"] = 0
            self.overlay.post(mute=True)
            return "Copy, going quiet. Only answers from now."
        if self._RE_CHATTY.search(t):
            self.cfg["talk_level"] = 2
            self.overlay.post(mute=False, talk=2)
            return "Copy, more feedback."
        if self._RE_NORMAL.search(t):
            self.cfg["talk_level"] = 1
            self.overlay.post(mute=False, talk=1)
            return "Copy, normal coaching."
        if self._RE_THEO.search(t):
            tb = c.theoretical_best()
            return f"Putting your best corners together gives {fmt_time(tb)}." if tb else "Need a few laps first."
        if self._RE_TARGET.search(t):
            tg = c.target()
            if not tg:
                return "I don't have a target time for this car and track."
            best = self._clean_best()
            line = f"The target is {fmt_time(tg[0])}, {c.target_words()}."
            if best is None:
                return line + " No clean laps of yours yet."
            pace = c.pace_pct(best)
            gap = best - tg[0]
            return line + (f" Your best is {fmt_time(best)}, {tenths(gap)} off, {pace:.1f} percent." if gap > 0.05 else
                           f" Your best is {fmt_time(best)}: you're on it.")
        if self._RE_CONSISTENCY.search(t):
            cons = consistency_of([x["time"] for x in hist if not x.get("pit") and not x.get("invalid")])
            if not cons:
                return "I need three clean laps to judge your consistency."
            best = self._clean_best()
            advice = pace_advice(c.pace_pct(best) if best else None, cons)
            return (f"You're {cons['label']}: your clean laps vary by about {tenths(cons['sd'])}"
                    + (f", not counting {cons['off']} slower lap{'s' if cons['off'] != 1 else ''}" if cons["off"] else "")
                    + "." + (f" {advice}" if advice else ""))
        if self._RE_PACE.search(t):
            clean = [x["time"] for x in hist if not x.get("pit") and not x.get("invalid")][-5:]
            if not clean:
                return "No clean laps yet."
            if len(clean) == 1:
                return f"One clean lap so far, {fmt_time(clean[0])}."
            avg = sum(clean) / len(clean)
            spread = f", laps within {tenths(stdev(clean))}" if len(clean) >= 3 else ""
            return f"Averaging {fmt_time(avg)} over the last {len(clean)} clean laps{spread}. Best of those {fmt_time(min(clean))}."
        ask_best = bool(self._RE_BEST_LAP.search(t)) and not self._RE_LAST_LAP_ONLY.search(t)
        if self._RE_LAST_LAP.search(t) and hist and not ask_best:
            last = hist[-1]
            h, best = last["time"], self._clean_best()
            tag = "a pit lap" if last.get("pit") else "invalid, so it doesn't count" if last.get("invalid") else None
            if tag or best is None:
                return f"Last lap {fmt_time(h)}" + (f", {tag}." if tag else ".") + (
                    f" Your best is {fmt_time(best)}." if best is not None else " No clean laps yet.")
            return f"Last lap {fmt_time(h)}, " + (f"{tenths(h - best)} off your best." if h > best + 0.005 else "that's your best.")
        if ask_best and (c.best_time or hist or not re.search(r"\b(why|how|should)\b", t)):
            best = self._clean_best()
            return f"Your best is {fmt_time(best)}." if best is not None else "No clean laps yet."
        if self._RE_RESET_REF.search(t):
            c.clear_reference(delete_file=True)
            return "Reference cleared. Next clean lap becomes the new one."
        cap = getattr(c, "capture", None)
        m = self._RE_CAPTURE.search(t) if cap is not None else None
        if m:
            secs = None
            if m.group("n"):
                n = m.group("n")
                secs = (int(n) if n.isdigit() else self._CAP_WORDS[n]) * (60 if m.group("u").startswith("minute") else 1)
            return cap.arm(secs)
        if cap is not None and self._RE_CAPTURE_STOP.search(t):
            return cap.stop()
        question = bool(self._RE_QUESTION.search(t))
        if self._RE_BRAKE_TONES.search(t) and question:
            mode = {"off": "off", "all": "on every corner"}.get(self.cfg.get("brake_callouts"), "on your focus corners")
            return f"Braking tones are {mode}. Say braking tones off, on, or all corners to change that."
        if self._RE_SPLITS.search(t) and question:
            return ("Split deltas are on. Say split deltas off to stop them." if self.cfg.get("split_callouts")
                    else "Split deltas are off. Say split deltas on to hear them.")
        if self._RE_BRAKE_TONES.search(t):
            if self._RE_OFF.search(t):
                self.cfg["brake_callouts"] = "off"
                self.overlay.post(tones="off")
                return "Copy, braking tones off."
            if self._RE_ALL.search(t):
                self.cfg["brake_callouts"] = "all"
                self.overlay.post(tones="all")
                return "Copy, braking tones on every corner."
            self.cfg["brake_callouts"] = "focus"
            self.overlay.post(tones="focus")
            return "Copy, braking tones on your focus corners."
        if self._RE_SPLITS.search(t):
            on = not bool(self._RE_OFF.search(t))
            self.cfg["split_callouts"] = on
            self.overlay.post(splits=on)
            return "Copy, split deltas on." if on else "Copy, split deltas off."
        if self._RE_REPORT.search(t):
            path = c.snapshot_report()
            if path:
                if sys.platform == "win32":
                    try:
                        os.startfile(path)
                    except Exception:
                        pass
                return "Report's open on your screen."
            return "Need a few laps first."
        if self._RE_FUEL_NEED.search(t) and c.last_frame and c.crew:
            return c.crew.fuel_need(c.last_frame)
        if self._RE_TYRES.search(t) and c.last_frame and c.crew:
            return c.crew.tyre_report(c.last_frame)
        if self._RE_DAMAGE.search(t) and c.last_frame and c.crew:
            return c.crew.damage_report(c.last_frame)
        if self._RE_ENERGY.search(t) and c.last_frame:
            return self._energy_answer(c.last_frame) or "This car doesn't use virtual energy."
        if self._RE_TEMPS.search(t) and c.last_frame:
            fr = c.last_frame
            parts = [f"{what} {v:.0f} degrees" for what, v in (("Water", fr.water_temp), ("oil", fr.oil_temp)) if v is not None]
            return (", ".join(parts) + ".").capitalize() if parts else "No engine temperatures from this sim."
        if self._RE_FUEL.search(t) and c.last_frame:
            used = [h.get("fuel", 0) for h in hist if not h.get("pit") and not h.get("partial") and h.get("fuel", 0) > 0.1][-3:]
            if c.last_frame.fuel <= 0:
                return "No fuel data from this sim."
            amt = round(c.last_frame.fuel)
            u = fuel_unit(c.last_frame.game, amt)
            fpl = (sum(used) / len(used)) if used else (c.crew.fuel_per_lap() if c.crew else None)
            extra = self._energy_answer(c.last_frame)
            extra = f" {extra}" if extra else ""
            if fpl:
                return f"{amt} {u}, about {_laps_left(c.last_frame.fuel / fpl)}.{extra}"
            return f"{amt} {u} in the tank.{extra}"
        if self._RE_NEAREST.search(t) and c.last_frame:
            f = c.last_frame
            crew = c.crew
            out_lines = []
            if ("behind" not in t or "ahead" in t or "front" in t or "nearest" in t or "around" in t) and (f.car_ahead or f.gap_ahead):
                desc = crew._nearest_car_desc(f, "ahead") if crew else ""
                gap_s = f", {f.gap_ahead:.1f} seconds ahead" if f.gap_ahead is not None else ""
                out_lines.append(f"Car ahead is {desc}{gap_s}." if desc else f"Car ahead is {f.gap_ahead:.1f} seconds up the road."
                                 if f.gap_ahead is not None else "There's a car ahead, no gap yet.")
            if ("ahead" not in t and "front" not in t or "behind" in t or "nearest" in t or "around" in t) and (f.car_behind or f.gap_behind):
                desc = crew._nearest_car_desc(f, "behind") if crew else ""
                gap_s = f", {f.gap_behind:.1f} seconds back" if f.gap_behind is not None else ""
                out_lines.append(f"Car behind is {desc}{gap_s}." if desc else f"Car behind is {f.gap_behind:.1f} seconds back."
                                 if f.gap_behind is not None else "There's a car behind, no gap yet.")
            return " ".join(out_lines) if out_lines else "No cars close ahead or behind right now."
        if self._RE_PIT.search(t) and c.last_frame and c.crew:
            return c.crew.pit_advice(c.last_frame)
        if self._RE_DEBRIEF.search(t) and hist:
            return c.after_race_debrief(c.last_frame, time.monotonic(), speak=False)
        if self._RE_SETUP.search(t) or self._RE_SHEET.search(t):
            s_line, c_line = c.collaborate_race_setup(c.last_frame, time.monotonic(), speak=False, use_openai=False,
                                                      user_query=t, show=bool(self._RE_SHEET.search(t)))
            if c.crew and c.crew.on("strategist"):
                c.crew.say("strategist", s_line, time.monotonic(), urgent=True)
            self.voice.last_text = f"{s_line} {c_line}"
            return c_line
        for _w, p_key, p_desc, p_named, p_to in self._PERSONAS:
            # "<style> coach / style / mode / personality", or "switch / change / set ... to <style>" with one of those
            # words: a question that just mentions a word ("coach, how was my exit?") never changes the coach.
            if p_named.search(t) or (self._RE_PERSONA_SWITCH.search(t) and self._RE_PERSONA_WORD.search(t) and p_to.search(t)):
                self.cfg["coach_personality"] = p_key
                self.overlay.post(persona=p_key)
                return f"Copy, coach personality set to {p_desc}."
        return None

    def _ask_openai(self, text):
        prov = ai_provider(self.cfg)
        name = AI_PROVIDERS[prov]["name"]
        now = time.monotonic
        if not ai_key(self.cfg):
            msg = f"I can't chat yet. Add your {name} API key in Settings."
            self.voice.say(msg, now(), "answer")
            self.overlay.post(rc_t=now(), rc_reply=msg, rc_ai_fail=f"No {name} API key")
            return
        model = ai_model(self.cfg)
        self.overlay.post(rc_t=now(), rc_thinking=model)
        t0 = now()
        with self._lock:
            recent = list(self.history[-6:])
        messages = [{"role": "system", "content": build_system_prompt(self.cfg)}]
        messages += [{"role": role, "content": msg} for role, msg in recent]
        data = json.dumps(self.coach.summary(), separators=(",", ":"))
        messages.append({"role": "user", "content": f"SESSION DATA: {data}\n\nDRIVER SAYS: {text}"})
        try:
            reply, who = ai_chat_ex(self.cfg, messages)
            reply = reply.replace("*", "").replace("`", "").replace("#", "").strip() or "Say again, I didn't catch that."
            with self._lock:
                self.history = (self.history + [("user", text), ("assistant", reply)])[-12:]
            self.overlay.post(rc_t=now(), rc_reply=reply, rc_ai=f"{who} · {now() - t0:.1f} s")
        except Exception as e:
            reply = openai_problem(e, prov)
            failed = AI_PROVIDERS.get(getattr(e, "ai_provider", prov), AI_PROVIDERS[prov])["name"]
            self.log(f"{failed} error: {type(e).__name__}: {e}")
            self.overlay.post(rc_t=now(), rc_reply=reply, rc_ai_fail=reply)
        self.voice.say(reply, now(), "answer")
        self.overlay.post(tip=reply)

    def _ask_openai_setup(self, text):
        """Collaborative Strategist + Coach race setup recommendation powered by the chosen AI."""
        now = time.monotonic
        model = ai_model(self.cfg)
        self.overlay.post(rc_t=now(), rc_thinking=f"{model} (Strategist + Coach setup)")
        t0 = now()
        s_line, c_line = self.coach.collaborate_race_setup(
            self.coach.last_frame, t0, speak=False, use_openai=True, user_query=text
        )
        src = (self.coach.last_setup_briefing or {}).get("source", ai_label(self.cfg))
        combined = f"Strategist: {s_line}  |  Coach: {c_line}"
        with self._lock:
            self.history = (self.history + [("user", text), ("assistant", combined)])[-12:]
        self.overlay.post(rc_t=now(), rc_reply=combined, rc_ai=f"{src} · {now() - t0:.1f} s", tip=c_line)
        if self.coach.crew and self.coach.crew.on("strategist"):
            self.coach.crew.say("strategist", s_line, now(), urgent=True)
        else:
            self.voice.say(s_line, now(), "answer")
        self.voice.say(c_line, now(), "answer")
        self.voice.last_text = f"{s_line} {c_line}"




def bind_button(cfg, action="ptt", status=print, timeout=20):
    """Command-line binding: wait for a wheel button and save it for `action`."""
    ctl = Controls(cfg, log=status)
    done = threading.Event()
    result = {}

    def got(b):
        result["b"] = b
        done.set()
    time.sleep(1.0)
    status(f"Press the wheel button for: {dict(BUTTON_ACTIONS).get(action, action)}")
    ctl.capture(got, timeout)
    done.wait(timeout + 2)
    if result.get("b"):
        ctl.bind(action, result["b"])
        status(f"Saved: {ctl.describe(action)}")
        return True
    status("No button pressed.")
    return False



VOICES = [
    ("Ryan (British)", "en-GB-RyanNeural"),
    ("Sonia (British)", "en-GB-SoniaNeural"),
    ("Thomas (British)", "en-GB-ThomasNeural"),
    ("Andrew (American)", "en-US-AndrewNeural"),
    ("Guy (American)", "en-US-GuyNeural"),
    ("Christopher (American)", "en-US-ChristopherNeural"),
    ("Jenny (American)", "en-US-JennyNeural"),
    ("William (Australian)", "en-AU-WilliamNeural"),
    ("Connor (Irish)", "en-IE-ConnorNeural"),
    ("Google (British)", "google:en-GB"),
    ("Google (American)", "google:en-US"),
    ("Google (Australian)", "google:en-AU"),
    ("Google (Irish)", "google:en-IE"),
    ("Google (Canadian)", "google:en-CA"),
    ("Google (Indian)", "google:en-IN"),
    ("Google (South African)", "google:en-ZA"),
    ("Kokoro George (British)", "kokoro:bm_george"),
    ("Kokoro Lewis (British)", "kokoro:bm_lewis"),
    ("Kokoro Daniel (British)", "kokoro:bm_daniel"),
    ("Kokoro Fable (British)", "kokoro:bm_fable"),
    ("Kokoro Emma (British)", "kokoro:bf_emma"),
    ("Kokoro Isabella (British)", "kokoro:bf_isabella"),
    ("Kokoro Heart (American)", "kokoro:af_heart"),
    ("Kokoro Bella (American)", "kokoro:af_bella"),
    ("Kokoro Sarah (American)", "kokoro:af_sarah"),
    ("Kokoro Nicole (American)", "kokoro:af_nicole"),
    ("Kokoro Sky (American)", "kokoro:af_sky"),
    ("Kokoro Michael (American)", "kokoro:am_michael"),
    ("Kokoro Adam (American)", "kokoro:am_adam"),
    ("Kokoro Fenrir (American)", "kokoro:am_fenrir"),
    ("Kokoro Puck (American)", "kokoro:am_puck"),
]
_VOICE_NAMES = [n for n, _ in VOICES]
_VOICE_BY_LABEL = dict(VOICES)
_LABEL_BY_VOICE = {v: n for n, v in VOICES}
_WHISPER_NAMES = [n for n, _ in WHISPER_MODELS]
_WHISPER_BY_LABEL = dict(WHISPER_MODELS)
_LABEL_BY_WHISPER = {v: n for n, v in WHISPER_MODELS}
_UPDATES_BY_LABEL = dict(CREW_UPDATES)
_CHATTER_BY_LABEL = dict(CREW_CHATTER)
_LANGUAGE_BY_LABEL = dict(CREW_LANGUAGE)

C = {"bg": "#0b0f14", "panel": "#121821", "panel2": "#19212c", "line": "#263142", "fg": "#e6edf3",
     "mut": "#8d99a8", "acc": "#3d8bfd", "acc_hi": "#5d9fff", "acc_fg": "#ffffff", "hover": "#212c3a",
     "good": "#34d399", "bad": "#f87171", "warn": "#fbbf24", "tip": "#fcd34d", "teal": "#5eead4", "violet": "#c4b5fd"}

_ICON_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAYC0lEQVR42tWbd5xc1ZXnv/fe9ypXVydFUECAAAkRhAhGMkJYtgED"
    "xrNuWOw1jJmdkfk44bDrXc+O23JgcBh2WGNmBrNjy5GPhHGEWRMtk0UQWEJCICGBhLLUsfK79+wfr2J3dRDz19Tn05+qfvXurXfy"
    "Ob9zLkzmJaKW9z7mAYr/AK/ljz3m0durJ3PvhAT1rF1r1l1zja3efO531p4wVC6fZkv2hKivO9riUeVwwIjf0w3/a1p83/BBj7oI"
    "ptX3Dfc0rPF80xfxI7vSmcTW31y+ZIc0P7sD5NgZ0NurWb1aAHnvd3489e08H/WMvibpm8Xt7ZlIRyrBoeECL+45hG80DlXZrfKu"
    "Klsr1fy5dq16b/2ztPy+uq7FvpV3rRW+gogtl5PxyMttkcgvZ6X9H99z9bK9DbS4yTOgVzSrlRMRdcbqNTdHIt6XTpw5fdq8ziRd"
    "MY9ExLMdyZg8u3Mftz/6EsmojxWpEStjEjua6LEIlVZMq77r0XuLiFLaGC8eJ51M0GnkSFc8ctuC3OvfuWvVqnKjJo/LgJ6etWbd"
    "umvspbf+5Pg9hWDNicfNuOScGRmmpWNBxBhddk4NFsoqcI6X9hzilxtfJ+Z7OEZLX96BFoxkiIynWQ3XVGhyIs6KFXHKj3idXd3M"
    "8Hm625Svf/D6S7e3YoJq1vpevXr1aresd838rOYP58+fM/eMaW1l32gvX7Zq6/4jbNpziF1HBzmaLRCI4HumvlULdR2tDeMxojVD"
    "ZFxT0CAOyQ7CYD9SyKMQiEQlSKaDxPFz/Tkd6f3TtbvsoY+//6WRTFAjbX7lt+6ecTirn1px+olzTutOB6KU99qBozywaQdb9x6B"
    "ckAkGWNGexoUHBzKo7UaV52bGTG2LU+kEdK4vupoy0Xcvt1w+ACUSpXtwt9TnodNtwX+yQu9ebOOO3hS0lz46+ves6Nq4gBelRE9"
    "WxaqtSIs+p///Itli06Zc1p3KrCI98S2t/jVC6+RyxU48bgpXH3OfM6ZO5350zpZv203X1j3R9LxCE5knDBap1PCR6P6Nt6akd+r"
    "hqUoBaUC7s0dIfEojGcoW4eIEPE9nLWYvqNeedMLwZvGTPVnTF376QceuHD/8LpgHaJAiamFi9XX2HsL0z9z8pzjV104p7uslPIf"
    "3/YWv3jmFQLr+MuLzuLrf3ERy0+ZzXHtaTqTMV4/0McDm3YQ9Qyj6Jexw44a6waZVFKCknAP2bcbDrxdUSBNfjhLMhEnFY8yMDAE"
    "2qCNQZdLujjYX5YZc44vlkzw//7LBx/rWbvQbFm3ThQiCqV4zy1rOvuHC69dff7C9hltcV7de0Tf+cjzFAPLl65Yyg3vPhPrHEeG"
    "8zy29U02vX2IbQeO8tqBPjyjRzurVqbQQv1lXJNoYR4V1ZdCFnn9FcjnwWhKxSJfuPYKbrpqJYlYlAef38Tn7vwpg7kCxvcAxJ60"
    "QObNn19Y0JY85VcfW7GH3l7tLf/qH816CPYdGbh+0UkndE5NxoJcMfDuf+l1ckN5/nLlOdyw7AyK5TLP7dzHt+9/mm1v7gcnEI+S"
    "TsRwriqSFmo9wTU1rvAbbhy5z2A/FPJ4RjM8lOWGKy/h26uuq339sfcuJRb1ueYrt+OH5qCk77Dts6ckDhYLfw30Lr/4Yq3Xf/Vi"
    "KyLKU/ojJ3SlJeIZ9erbh3ht9wFOOq6bv754MdYJz+3Yy6fX/Bvbdu3n3afP40ef+TDfuvYSCsUSBlAiUP1zDZ9FQFyLaw3fiaCc"
    "NO/Rch8JOREEyNAAOIcVwfgen/7Q+3DOUbYW5wTrHFdecDazZkyhUCyDgCkX9dDggPTnS9f2PvaYt37FxdZDKVn8hTvmpOKRM7vj"
    "ngqCQG96az+2UOLqJacytS3JvoFhbv39k+QGc9z8wWV857r34hnNg5vfoJwvkopFcdailJq8KY/l6MZbLxKqfzEP2SE0ikKhxEmz"
    "pnP6CbPQWofbiaCVpr+Qo1QOUCpknFJaB4WC5JLx+S/uc6eAekUD5G3p9I62tJ/wPTuYL6o3D/YRTcQ4Z+50FPDHV3by+ht7WXr6"
    "CXz3I+9Fa8XBwSz5Upnjp7QznC+gqw8ooSTVsWiCq2sCrmF9K00AGB6EQh5tNK5QZMVZC4j6HoF1KAhNEnhmy3YOHDhM1PcQEYjG"
    "UErbovbUQLZwZq2kkLKb155K0JGKSxBYjg7lmNmeYv6MbuIRj81v7YdSmc9eej5Ga4YLJfqzBa48ez4vfvNvOHv2NPLFUrhZw8Oq"
    "8VR5or8mRrg68TZABvvA2pAoo7h62ZKW/uTB5/4M1qKlkjMk0wCUraNs7bwaA6K+135oIMuzr73JS7v2YQMLIqzfspNfP7eFbXsP"
    "4yVi7DzQx30btvCnrbuYP6OLcuCYkk7wV8vPolwohSl6gySbtGEy9j0Go+p7gOSzMDSAQlEoFJl7/AwuOuu0SnAIWeAZTTmwPPT8"
    "JnQ0EppnJIqKJ1EiWOuwTjpqiVAmFmHjjj08vOEIvucR8T0O9g/zxTUPAIpY1CcRj/DlXzyELZaZOa2Dzd/9NB3JGACPv/omWmvE"
    "NUhqhIGryiVRx+gYpO4YlBZkoA8KBYxnsEMFrl52DolohMA6PKOxzmG0ZsPW7by2aw+xeAxnLSRTKD+Kcq5inuH2HoDD4WtNIuKh"
    "tUFE0EqRjkUqaaUgzpGKeJh4hMMDw1x6yxr+89JFbNy5n3ue3kQyFsEGbsIwWHVSotSkwmR9YZj5Sf8REEdgFZF4jBsuXR5KX9X9"
    "JMAv12/AFkvoeAynNCqVCesGG2q3rnAgTIUdiHM461DVXFwEJ81JibMO54S477Hxjb1sePUt8DTpRAwRN3bMHrMOlzARarmmoi7V"
    "sGAEGTgC2WGMNuSyOS654CzOOnkuzkmogSJ4RpMrFPn1489hYlGstRCLh/bfZG4NGkCDB2fMnL7+hM4KCd9DR30ECCpetzXR4+T+"
    "TTXCeIWEhkIeOXIwlKDnIdbx2Q9fVnn0cHPrBGMUv39qIzvffJtkJo0NAkimUZE4VE1UBBo1QDd+UXE2E6mlc46QbtVUgU2oyhNA"
    "UzJqjQqN9Mh+ZHgIYwy54SxLzzmdK5aegxPBGF0xA4UCfvC7h0POOgFjUG0dIROdC5+plQaohrDzThMZVVFbacm88TWhMTWWxmtK"
    "IQNHkMMHQt9REdItq65DKYVzDpSqOb9nt7zO+uc2EU/GsTaAdAaVbANn67/VoOUVH9CsAapqm+8gt584v2+1ppk5qgavadzwAG7/"
    "biiV8CMRho7281fXfoCLzl5QI7rx9e2f/ZZyqUQkHsWiUJlO8PyQRlX5DSfh/+P5gCYixnnYyWEAk2We1AERQIb6kAO7IZfDeB7D"
    "w1lOOXkut33mhtDxVe6rMuKZza/xm0efJp5KYssBJJLoto665tTorKPYFQa45mSkobIbW5otqBmDKc35fdW7N7xXUYIqx0pF3OBR"
    "5OhBKBXxPI9SsUQyGuHn3/g8bckEzjmU0k0P93d33YO1Fg1YQLV3QSQG1tW2bvJzjWGwTry0pGjMRKalVKvirxOpZAS+10iwCARF"
    "pFxEcsPI8ADksyCC5/vkC0U0sPZbX2bxKfOw1tUcX2AtnjH8/MHHefjJ50lm2kLPn0qh27uaiG30dSN8wDhhsGUiM5mMrrJWN0pX"
    "UM4hziI2gKCMlItQKiKlApQKEARhX8QYMJqhvgFmTp/CT275IpcsWVTL+KqRyBjD7oNHuPkf7iYSq2R9WqE7poAfq9i6ahJOmAm6"
    "ESbgxguDDUnJKLUe4RMqJWvtFZSRoFQntFyEcgkJyuFDOFcpVRXaaJQxBNYxPJwFJ1y54gK+9z9uYs6MKdgG4kUkVDTgxq99j0OH"
    "+khmUtggQGU6UZmuGpFNtFQ1fbQGuAkSoRa23QhShuIOJR2UkVIeyWeRYg4pFcEGlQgT4ndaq9CGjcY6oRQEBNk8WEuiLc373rWY"
    "m675AFevuKDu6BqIt9bheYbP3fZ/efhPG0h1tROUg7DknTITtBfSpFTdBKRB00dpQCsTmIQm1BisNBKUcLlBJDuIFHNgLQpCYFJp"
    "RAmBdRRLJaQchLFZabx4jOndHZw5fy7Lz1nE5Redy8IT59QlDbVwJyI4ETzP8I271/KPP7yXVGc7thygtEZ1T0fFUw1hT0ZrQMtE"
    "SMZJhMYMX5U0NQhCwof7kGIecYI2Gm0M5cBSGM5BOQDPkG5Lc8Jx0zh59kxOmzebhSfPZcG82Zw4awbt6WTDc4aEmirKAzXnZ5Ti"
    "b7//E2656x6S7W2h3SOojm50e3cY9saMVC1S4ZFOULVMSVtwRCkkn8UNHEZyQyBSd165HJQC2joznLdkERctOYNzF83n9JPnMmv6"
    "FHzPG7Wrc4ITh66YiGmI86Fj1AwM5/jEN+/gnt8+Qqojg3NhH0B1dKG7Z4bP5VwIzzU660YfNSoKtMgDKr2VZm2oMSV0gW6oH9d/"
    "CMpFlDZozzA0nAPnuODshXz0qvdw6bvP46TZM1sQ62rNFK1U6AS1Qlf64iKCc4LSqqb+DzzxPF/8h7vZun0X6c4Mga10vjOd6CnH"
    "g/Hqqj9W1emkRSbYlAc0h41mR1dXIzd8FDdwGAKL8T3KQUB2cJhl553J52/s4eqVS+sgqYQorUKhtEKh0FrXWvxSI9ihCYlWSmNM"
    "uP7xFzdz+09/w32PPIXSmnSmLXR4SodqP+W4errbClZtyEqb8MnRYdCFOtOyLRXuIiK4oSO4wSPgHJ7vMzSUJZNOctvXP89NH7mq"
    "HgGtDQlVCs+YhvAV4goCKBVKWDU0QvIB7NjTz/pnn+N3jz7GIxv+TFAsk8ykwn1LZfA9VOc0dOe0lpIfO3K1MgE3GTwg5KwM94WS"
    "d4LnewweHeCsRfP56W3/i4Unz62prjG6RrSrSLeJ2CaFcuzef5SN2/aQDl7E9T/L0y9vZ82fSuzYkyLZHSMWi4ZYpVKoRArVNRWV"
    "aq+UubYe7tQEpXjV2TMZQKTq6SUcSnC5QezAIbAWz/cZPDrAyuXnce/3v0YmnSQILJ5naqrrKnamdRgRAPKFIjt272Pr9jfZvH0X"
    "23btYesbu9m99zBfv/xVPnbBQdJdhpWXR/m7yyKs/h2svj9GIh6gYnFUugOV6UL50YrtuAq8JuNjijUaqcPzo5ygE0IMeTQeJ6U8"
    "buAQBEFIfP8AK5Yt4fd330o04tcSk5EhDGDHW3t58InnefSZjbz86g52HzhMIZsP1dbXUI7x5b/o45NX5wj6uwhEcHmH1kLvh/bw"
    "8qE0v35jHm1TUjg/Tq2ErzjkUQXbeBGsVg43aIC2NGP4IxEZF+AGDyPFAsbzyA3nOPWkufzyn74REt+QpbkKoGqU4skXN3P7D+/l"
    "wSdeYKBvAIzGi0WI+D7pTLoG2mgcN144hBvSOBegFRgNgVOYQPivF2X5Td80lFduSG/VKIc3quocA10enQdUnGBTIlRDcTQuN4jL"
    "DaGUwgaWiGf42e1foaMt1VSZOefQWpMvlvjb7/6A7625j6BcJp5K0taRQZBK3HbYQFBGUxaPKe2aTNyGgmicB1OgnGJqPE9El3G2"
    "RVY3Al0eG8eAJn/HWOWwbkCEUGF6m+0H59C+x9DRAW77+udZvHB+zeYbiX/7wGGu+eRXeOrpjaS6OtCJGIG1BEEZjIFILGxS+OFf"
    "1Pfp01H25XbTme7DWg+vUpIHThExjjcGUhRKhli8hBU9qS5ynREj0vfWmOBoULTKWJcfREoFjNZkB7Ocd+4Z3Pzxnork615eKcWh"
    "o/1cev0X2Lx1O+1TuyiVg7BPF4miEml0LImKxMKwpU041aGF4UKE//P8fH7woSeJWE3ZhkQmomVcYLjjxVPwta3hgZOC6caC52oM"
    "GAWJjawGFWJLSH4oNAsJ88Jbv/SJShiTSq0hiBMcwkc/+zU2v/Iame5OSsUiGINOdaBTHahIrLkZYsPQZQXaIgXWvDyHKfEC/33p"
    "FtrjJRDYPZjkS48u5qk93aSjJazTk+89twJsqxnd6FqgVTUoSH4IKRUxnmGwf5ArL7uYFe9aPMLuw5j/1X/8Vx568HEy07spl0oo"
    "46Ez3ehUHZJW1dE5VW++hDN+kPDL/P1Tp7Lu1VmcNb2PsjVs2NfF/lycTLSEcyokQv07AFuh3rUelQc0taAVuDKukA3jrA0zuS/+"
    "zXVN/HcV77/p1Te49fs/JlmtyZVCpzvQifbKnrZGdBWOGllsiVN0RIu8PRhj+9HjUUqRiFjaI8VQ8kpaq/WxArbSojfYlAmGcQlX"
    "yiHlAlobssNZ3v2uxVx0/lk1iTe+vnTrP1HMF4lEo1gboBPtDcTTgA824v916VevWQsRHRCLhkx0orBWjcAp/52Aba0OGA8QcYIU"
    "cmAd2te4cpkbr72iwdubmhmsf2Yjf3jkSVJtqRCU8CMh8ajKD6kJOkLNVac4hW0aJ5u4VXfMgG2Dqdc0oGobyoALSrhSAaUgny8y"
    "e87xfPD9F9Vq8sZhrtvu+gVSgaIdoBNplBdpyNQmSE8nqDo5hi7ypABbJ2OHwWo2KKUC2DLGGErZId63/HIybSmstRhjajF/6+u7"
    "eHj9BhKpJDYI0JEYOppqXVBN0mm1VutxpsWOBbAdCxHyFAO1GR9nkVI+dH6i0Mbw4SsuaaIpbEfDz+77A7nBITLdHQSBRUUSKF0v"
    "TWWSmGLL9thEGd0xAbY0QW06rCAG6gyI+Lt8HY6cYwMkKNZGUGbPnsHSc88Mp9QrxY2pjKD87qHHMbEozrow5kfiTdJXkx0AnSCR"
    "kUmtGQOwraT0Ui2anOBpRdRTO2sM6GrLbH5LH7IKjAQlIQiUNopSrsCFS84glYzXnF71fcPGzWzZup1EMoFzFhWJo4zfophqJY0x"
    "NGGMLvLYrfPJa0etdBIxUbGkEomXq0NS6mf/+3M7k7HIJt/zxQUlJ+Iq3HIsO/+sCoojDYiO8IfHniEoFGujKdqPhduNGJJqAlvd"
    "GANTE0yL1Yel3Bjjd5MbwBLrnO/5KuHpHVe8//StgNLLl/capZS0pRP3pJMJZQMnYZ8//EsmYpX1dSYopVj/1Aso3w/VX5nQ87eY"
    "AG3JiHc4LTaKEcewBgTrrEslEmQS0XtXLVlSXt7ba/T69aE7nNqd/FEm6Q9q42lQIiJoz3Dvbx9Ga0XE91BK4XmGP2/ZzvMbXyGR"
    "iIVQl/Hqzm+MUdixZwDHH6Edj8DW47Vu9BonKCeCoDuiujg9E/sXgIvBGVgvPT1rzdof3jR0+pKVqhiwcrDvUKAQ48cibNm6g/6B"
    "IRaeOg+tFU8/t4kbP7uaQ0f68H0fEcHEUqhIou6uhMmNwldbZce0ZrwR/NY3KqUo28B2dnWZmR3J2/7tm59c17N2rbnzU59yqnZg"
    "oqdHr1y5Uv/wgVef3L79jXOzfXsD44Vz5sNDw3RP6SLTluKtt/cjAvF4Rfqej9c2FeVFw9pbTXx6ZLyTIjLZg1ZjnB0aeVZJheMz"
    "1o8lzInT27cuPvPUJTP2vlBYvfqrAqqGLsiCBQtk1apV5VmzOq+dM3vWgUii3bNBOQChLdNGNpvnrbf3E41EiNeGozUmnkHpEJNX"
    "FbUcV6XdRI5uko7Sjecj6h0uG1irjWdmT8kMzOhs77lr1VW51fXYVD+euH79eunp6THrfnTH0fOWXvawF4t/aDhfaivmsmWlRGut"
    "lGd0rVmpjI9JtKMjyVF6qVqE6GN9qVHRVMYxidGmpxUSBC6IxmLe3Gmd/ce1xz9w/99/8sWenrVmy52fcqPOZwJs2bJFenp6zH0/"
    "v3Pf+Rdf/ttYLHW+ePHZuXxBiRBo7aH9qDLRJF68DeXHxj2Fpxo7aeMGazVh/G5KD0e3pusWIDjrrHWC6ezsNHOmZDbN7Ipddf+3"
    "bn6+eiRwwl/u6ekx69ats729ayNPvLbxy4ePDHyubzDfNjQ8TGADlFIWpcOaY9Ln/ybjCybwDyP31g17C0qUMp4fIZVO0Z6I5qa2"
    "p+44bvaUr/30v12fbUX8uKyvniEEuHZV79zDfcWP9w/n/lMuX1hYDIRy4HDVcldN9pxQhYhxHNi4DG3co+Ga1hrfM0QMJOORbZlU"
    "8ledHal/ve8bN70+kpZjPTytenp69Lp162wlC9TX3nTLgoGh3KJiqTzPOtdRKz4bx2JUC+RWNx56VjjGOBytGX3QWulxD1x7xvRF"
    "o/7OZCK5+TOXfuKVFStU0HAK1r0zLzTiIPXy5b0e/0Fey3t7J318/v8Do5KWu1hO1kQAAAAASUVORK5CYII="
)


def _win_dark_titlebar(win):
    """Windows 10/11: dark title bar, and on Windows 11 a caption + border in the app's own colours."""
    if sys.platform != "win32" or ctypes is None:
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4) == 0:
                break
        def rgb(h):
            return ctypes.c_int(int(h[5:7], 16) << 16 | int(h[3:5], 16) << 8 | int(h[1:3], 16))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(rgb(C["bg"])), 4)
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(rgb(C["line"])), 4)
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(rgb(C["fg"])), 4)
    except Exception:
        pass


def _open_path(path):
    """Open a file with its program (console mode; the app has its own App._open)."""
    try:
        if sys.platform == "win32":
            os.startfile(path)
        else:
            import webbrowser
            from pathlib import Path
            webbrowser.open(Path(path).resolve().as_uri())
    except Exception as e:
        file_log(f"Couldn't open {path}: {e}")


def _game_window():
    """Windows: the foreground window when another program (the game) has it, else None."""
    if sys.platform != "win32" or ctypes is None:
        return None
    try:
        u = ctypes.WinDLL("user32")
        u.GetForegroundWindow.restype = ctypes.c_void_p
        u.GetWindowThreadProcessId.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
        h = u.GetForegroundWindow()
        pid = ctypes.c_ulong(0)
        if h and u.GetWindowThreadProcessId(h, ctypes.byref(pid)) and pid.value != os.getpid():
            return h
    except Exception:
        pass
    return None


def _no_activate(win, user32=None):
    """Windows: a window the driver can click and tick without the game losing focus (WS_EX_NOACTIVATE), kept
    on top without being activated. Done on the withdrawn window before it's shown, and again after."""
    if (sys.platform != "win32" or ctypes is None) and user32 is None:
        return False
    try:
        ct = ctypes if ctypes is not None else __import__("ctypes")
        u = user32 or ct.WinDLL("user32")
        vp, ssz = ct.c_void_p, ct.c_ssize_t
        get = getattr(u, "GetWindowLongPtrW", None) or u.GetWindowLongW
        put = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
        get.restype, get.argtypes = ssz, (vp, ct.c_int)
        put.restype, put.argtypes = ssz, (vp, ct.c_int, ssz)
        win.update_idletasks()
        hwnd = int(win.wm_frame(), 16) or None
        if not hwnd:
            return False
        ex = get(hwnd, -20)
        if not ex & 0x08000000:
            put(hwnd, -20, ex | 0x08000000)
        swp = u.SetWindowPos
        swp.restype, swp.argtypes = ct.c_int, (vp, vp, ct.c_int, ct.c_int, ct.c_int, ct.c_int, ct.c_uint)
        swp(hwnd, vp(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0020)
        return True
    except Exception:
        return False


def _virtual_screen(win):
    """(x, y, width, height) of all monitors together (Windows), or the screen Tk knows."""
    if sys.platform == "win32" and ctypes is not None:
        try:
            gsm = ctypes.WinDLL("user32").GetSystemMetrics
            x, y, w, h = (gsm(i) for i in (76, 77, 78, 79))
            if w > 0 and h > 0:
                return x, y, w, h
        except Exception:
            pass
    return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight()


def _focus_back(hwnd):
    if not hwnd or sys.platform != "win32" or ctypes is None:
        return
    try:
        u = ctypes.WinDLL("user32")
        u.SetForegroundWindow.argtypes = (ctypes.c_void_p,)
        u.SetForegroundWindow(hwnd)
    except Exception:
        pass


class SetupSheetWindow:
    """The written race setup the crew just called on the radio: click any box to apply that setting directly
    in the sim (click again to revert), or click Apply all. Stays on top without stealing game focus."""
    _pos = None
    WIDTH = 600

    def __init__(self, parent, sheet, open_file=None, font=None):
        import tkinter as tk
        self.sheet, self.open_file = sheet, open_file
        self.sheet.setdefault("applied", set())
        self.font = font or (lambda size, bold=False: ("Segoe UI", size, "bold" if bold else "normal"))
        self.win = None
        self._last_status = ""
        game = _game_window()
        try:
            self._build(tk, parent, sheet, game)
        except Exception:
            try:
                if self.win is not None:
                    self.win.destroy()
            except Exception:
                pass
            self.win = None
            raise

    def _build(self, tk, parent, sheet, game):
        open_file = self.open_file
        w = self.win = tk.Toplevel(parent, bg=C["bg"])
        w.withdraw()
        w.title(f"Race setup · {sheet.get('title', '')}"[:100])
        try:
            w.attributes("-topmost", True)
        except Exception:
            pass
        w.protocol("WM_DELETE_WINDOW", self.close)
        w.bind("<Escape>", lambda e: self.close())
        w.minsize(460, 300)
        lbl = lambda master, text, fg=C["fg"], size=11, bold=False, bg=C["bg"], **kw: tk.Label(
            master, text=text, bg=bg, fg=fg, font=self.font(size, bold), justify="left", anchor="w", **kw)

        hdr = tk.Frame(w, bg=C["bg"])
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        lbl(hdr, "RACE SETUP", C["acc_hi"], 9, True).pack(anchor="w")
        lbl(hdr, sheet.get("title", ""), size=15, bold=True, wraplength=self.WIDTH - 40).pack(anchor="w")
        sub = " · ".join(x for x in (sheet.get("sim"), sheet.get("race"), sheet.get("conditions"), sheet.get("grid")) if x)
        if sub:
            lbl(hdr, sub, C["mut"], 10, wraplength=self.WIDTH - 40).pack(anchor="w")
        lbl(hdr, "Click any box to apply that setting in the sim (click again to revert).", C["mut"], 9).pack(anchor="w", pady=(4, 0))

        foot = tk.Frame(w, bg=C["bg"])
        foot.pack(side="bottom", fill="x", padx=16, pady=(6, 12))
        btn = lambda text, cmd: tk.Button(foot, text=text, command=cmd, bg=C["panel2"], fg=C["fg"], relief="flat",
                                          activebackground=C["hover"], activeforeground=C["fg"], bd=0, padx=12, pady=5,
                                          font=self.font(10), cursor="hand2", highlightthickness=0)
        self.close_btn = btn("Close", self.close)
        self.close_btn.configure(bg=C["acc"], fg=C["acc_fg"], activebackground=C["acc_hi"])
        self.close_btn.pack(side="right")
        if sheet.get("path") and open_file:
            btn("Open file", lambda: self.open_file(sheet.get("sim_setup_path") or sheet["path"])).pack(side="right", padx=(0, 8))
        self.copy_btn = btn("Copy", self.copy)
        self.copy_btn.pack(side="right", padx=(0, 8))
        self.apply_all_btn = btn("Apply all", self.apply_all)
        self.apply_all_btn.pack(side="right", padx=(0, 8))
        self.progress = lbl(foot, "", C["mut"], 9)
        self.progress.pack(side="left")

        outer = tk.Frame(w, bg=C["panel"], highlightthickness=1, highlightbackground=C["line"])
        outer.pack(fill="both", expand=True, padx=16)
        cv = self.canvas = tk.Canvas(outer, bg=C["panel"], highlightthickness=0, bd=0)
        sb = tk.Scrollbar(outer, orient="vertical", command=cv.yview)
        body = tk.Frame(cv, bg=C["panel"])
        cv.create_window((0, 0), window=body, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        body.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        wheel = lambda e: cv.yview_scroll(-1 if (getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4) else 1, "units")
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            w.bind(seq, wheel)

        body.grid_columnconfigure(2, weight=1)
        groups = OrderedDict()
        for idx, (area, setting, change) in enumerate(sheet.get("items") or []):
            groups.setdefault(area, []).append((idx, setting, change))
        applied_init = set(sheet.get("applied") or ())
        _, badges = SetupApplier.compute_state(sheet)
        self.checks = []
        r = 0
        for area, rows in groups.items():
            lbl(body, area.upper(), C["teal"], 9, True, bg=C["panel"]).grid(row=r, column=0, columnspan=4, sticky="w",
                                                                           padx=12, pady=(10 if r else 8, 2))
            r += 1
            for idx, setting, change in rows:
                is_on = idx in applied_init
                var = tk.BooleanVar(w, value=is_on)
                cb = tk.Checkbutton(body, variable=var, bg=C["panel"], activebackground=C["panel"], selectcolor=C["panel2"],
                                    fg=C["fg"], highlightthickness=0, bd=0, cursor="hand2")
                cb.grid(row=r, column=0, sticky="nw", padx=(10, 2), pady=1)
                s_l = lbl(body, setting, size=11, bg=C["panel"], wraplength=150)
                c_l = lbl(body, change, C["tip"], 11, True, bg=C["panel"], wraplength=250)
                badge_txt = badges.get(idx, "Applied ✓")
                st_l = lbl(body, badge_txt if is_on else "Apply", C["good"] if is_on else C["mut"], 9, is_on, bg=C["panel2"], padx=6, pady=1)
                if setting:
                    s_l.grid(row=r, column=1, sticky="nw", padx=(0, 8), pady=2)
                    c_l.grid(row=r, column=2, sticky="nw", padx=(0, 8), pady=2)
                else:
                    c_l.configure(wraplength=400)
                    c_l.grid(row=r, column=1, columnspan=2, sticky="nw", padx=(0, 8), pady=2)
                st_l.grid(row=r, column=3, sticky="ne", padx=(0, 12), pady=3)
                item = (idx, var, s_l, c_l, st_l, badge_txt)
                cb.configure(command=lambda it=item: self._ticked(it))
                for x in (s_l, c_l, st_l):
                    x.configure(cursor="hand2")
                    x.bind("<Button-1>", lambda e, it=item: (it[1].set(not it[1].get()), self._ticked(it)))
                self.checks.append(item)
                r += 1
        if not self.checks:
            lbl(body, "No setup changes on this sheet.", C["mut"], 10, bg=C["panel"]).grid(row=r, column=0, columnspan=4,
                                                                                           sticky="w", padx=12, pady=8)
            r += 1
        said = [(who, sheet.get(k)) for who, k in (("Strategist", "strategist"), ("Coach", "coach")) if sheet.get(k)]
        if said:
            lbl(body, "WHAT THE CREW SAID", C["mut"], 9, True, bg=C["panel"]).grid(row=r, column=0, columnspan=4, sticky="w",
                                                                                  padx=12, pady=(14, 2))
            r += 1
            for who, line in said:
                lbl(body, _crew_said(who, line), C["mut"], 10, bg=C["panel"],
                    wraplength=self.WIDTH - 70).grid(row=r, column=0, columnspan=4, sticky="w", padx=12, pady=(0, 4))
                r += 1
        tk.Frame(body, bg=C["panel"], height=8).grid(row=r, column=0)
        for it in self.checks:
            self._style_row(it)
        self._update_progress()

        w.update_idletasks()
        need = body.winfo_reqheight() + hdr.winfo_reqheight() + foot.winfo_reqheight() + 40
        h = max(300, min(need, w.winfo_screenheight() - 140))
        cv.configure(height=h - hdr.winfo_reqheight() - foot.winfo_reqheight() - 40)
        if body.winfo_reqheight() > int(cv.cget("height")):
            sb.pack(side="right", fill="y")
        home = f"+{max(0, w.winfo_screenwidth() - self.WIDTH - 60)}+80"
        pos = SetupSheetWindow._pos
        if pos is not None:
            vx, vy, vw, vh = _virtual_screen(w)
            if not (vx - self.WIDTH + 120 <= pos[0] <= vx + vw - 120 and vy <= pos[1] <= vy + vh - 60):
                pos = SetupSheetWindow._pos = None
        try:
            w.geometry(f"{self.WIDTH}x{h}" + (f"+{pos[0]}+{pos[1]}" if pos else home))
        except Exception:
            SetupSheetWindow._pos = None
            w.geometry(f"{self.WIDTH}x{h}{home}")
        if game:
            _no_activate(w)
            w.wm_state("normal")
            _no_activate(w)
            _focus_back(game)
            w.after(80, lambda: _focus_back(game))
        else:
            w.deiconify()
            w.lift()
        _win_dark_titlebar(w)

    def _style_row(self, item):
        _idx, var, s_l, c_l, st_l, badge_txt = item
        done = var.get()
        s_l.configure(fg=C["mut"] if done else C["fg"])
        c_l.configure(fg=C["good"] if done else C["tip"], font=self.font(11, not done))
        st_l.configure(text=badge_txt if done else "Apply", fg=C["good"] if done else C["mut"],
                       font=self.font(9, done))

    def _confirm(self, text):
        try:
            from tkinter import messagebox
            return bool(messagebox.askyesno("Apply setup", text, parent=self.win))
        except Exception:
            return False

    def _ticked(self, item):
        idx, var, *_ = item
        done = bool(var.get())
        applied = set(self.sheet.get("applied") or ())
        changes = SetupApplier.preview(self.sheet, (applied | {idx}) if done else (applied - {idx}))
        res = SetupApplier.toggle_item(self.sheet, idx, enabled=done)
        what = "; ".join(f"{lbl} {b} → {a}" for lbl, b, a in changes[:2])
        self._last_status = (("Applied: " if done else "Reverted: ") + what) if what else res.get("status", "")
        self._style_row(item)
        self._update_progress()

    def toggle_item(self, idx: int, enabled: Optional[bool] = None):
        """Programmatically click/toggle row `idx` and apply it in the sim."""
        for it in self.checks:
            if it[0] == idx:
                target = (not it[1].get()) if enabled is None else bool(enabled)
                it[1].set(target)
                self._ticked(it)
                return True
        return False

    def sync_from_sheet(self):
        """Refresh checkbox states and badges in place when `self.sheet['applied']` is updated externally."""
        applied = set(self.sheet.get("applied") or ())
        for it in self.checks:
            it[1].set(it[0] in applied)
            self._style_row(it)
        self._update_progress()

    def apply_all(self):
        """Apply all setup changes in the sim (or revert all if every box is already ticked). Applying asks first,
        listing every value that will change."""
        all_done = bool(self.checks) and all(it[1].get() for it in self.checks)
        target = not all_done
        if target:
            changes = SetupApplier.preview(self.sheet, [it[0] for it in self.checks])
            if not changes:
                self._last_status = "Nothing to change: these values are already set"
                self._update_progress()
                return
            listing = "\n".join(f"  {lbl}:  {b}  →  {a}" for lbl, b, a in changes)
            if not self._confirm(f"Apply {len(changes)} change{'s' if len(changes) != 1 else ''} in the sim?\n\n{listing}\n\n"
                                 "Before values are SimCoach's setup profile, which can differ from your garage setup."):
                return
        for it in self.checks:
            it[1].set(target)
            self._style_row(it)
        res = SetupApplier.apply_all(self.sheet, enabled=target)
        self._last_status = res.get("status", "")
        self._update_progress()

    def _update_progress(self):
        n, done = len(self.checks), sum(1 for _, v, *_ in self.checks if v.get())
        if hasattr(self, "apply_all_btn"):
            self.apply_all_btn.configure(text="Revert all" if (n and done == n) else "Apply all")
        cnt_txt = (f"All {n} applied in sim ✓" if n and done == n else f"{done} of {n} applied in sim" if n else "")
        extra = self._last_status or self.sheet.get("source", "")
        txt = " · ".join(x for x in (cnt_txt, extra) if x)
        self.progress.configure(text=txt, fg=C["good"] if (n and done > 0) else C["mut"])

    def copy(self):
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(setup_sheet_text(self.sheet))
            self.copy_btn.configure(text="Copied")
            self.win.after(1500, lambda: self.alive() and self.copy_btn.configure(text="Copy"))
        except Exception:
            pass

    def alive(self):
        try:
            return self.win is not None and bool(self.win.winfo_exists())
        except Exception:
            return False

    def close(self):
        if not self.alive():
            self.win = None
            return
        try:
            x, y = self.win.winfo_x(), self.win.winfo_y()
            if -20000 < x < 40000 and -20000 < y < 40000:
                SetupSheetWindow._pos = (x, y)
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass
        self.win = None



# --- update check: GitHub's latest release against this version ---------------------------------------------
UPDATE_REPO = "Jcedwar61/SimCoach"


def _ver_tuple(v):
    """'v6.2.1' -> (6, 2, 1, 0); anything without numbers -> (0, 0, 0, 0)."""
    nums = [int(x) for x in re.findall(r"\d+", str(v or ""))[:4]]
    return tuple(nums + [0] * (4 - len(nums)))


def check_latest_release(timeout=8.0):
    """The newest published release when it's newer than this copy, else None:
    {"tag", "version", "url" (release page), "notes", "installer_url"}. Raises on network errors."""
    import urllib.request
    req = urllib.request.Request(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": f"SimCoach/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    tag = str(d.get("tag_name") or "")
    if not tag or d.get("draft") or d.get("prerelease") or _ver_tuple(tag) <= _ver_tuple(APP_VERSION):
        return None
    asset = next((a.get("browser_download_url") for a in d.get("assets") or []
                  if str(a.get("name", "")).lower() == "simcoach-setup.exe"), None)
    ver = tag.lstrip("vV")
    return {"tag": tag, "version": ver, "url": d.get("html_url") or f"https://github.com/{UPDATE_REPO}/releases/latest",
            "notes": str(d.get("body") or "")[:2000],
            "installer_url": asset or f"https://github.com/{UPDATE_REPO}/raw/{tag}/SimCoach-Setup.exe"}


LIBRARY_URL = f"https://raw.githubusercontent.com/{UPDATE_REPO}/main/references/"


def library_file_name(key):
    """The shared library's file name for (sim, track, car): the same as the reference's own file name."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", "__".join(key)) + ".json"


LIBRARY_API = f"https://api.github.com/repos/{UPDATE_REPO}/contents/references"


def _library_get(url, timeout, limit=3_000_000):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": f"SimCoach/{APP_VERSION}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("library file too big")
    return raw


def _checked_library_lap(raw, name):
    """A downloaded library file, checked like an import: a usable reference whose sim / track / car match its
    file name, and a real (not provisional) lap."""
    d = json.loads(raw.decode("utf-8"))
    prob = ref_problem(d)
    if prob:
        raise ValueError(f"unusable: {prob}")
    if library_file_name(d["key"]) != name or d.get("provisional") or d.get("source") == "starter":
        raise ValueError("doesn't match its sim, track and car")
    d["source"] = "library"
    return d


def fetch_library_lap(key, timeout=8.0, base=None):
    """The library's reference lap for this exact sim / track / car, or None if there isn't one."""
    import urllib.error
    from urllib.parse import quote
    name = library_file_name(key)
    try:
        raw = _library_get((base or LIBRARY_URL) + quote(name), timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return _checked_library_lap(raw, name)


def list_library(timeout=8.0, api=None):
    """The laps in the shared library: [{"name", "sha", "size", "url"}] (sha changes whenever a file does)."""
    items = json.loads(_library_get(api or LIBRARY_API, timeout, limit=5_000_000).decode("utf-8"))
    return [{"name": it["name"], "sha": it.get("sha", ""), "size": int(it.get("size") or 0),
             "url": it.get("download_url") or ""}
            for it in items if isinstance(it, dict) and str(it.get("name", "")).endswith(".json")
            and it.get("type", "file") == "file"]


def sync_library_benchmarks(timeout=8.0, base=None, path=None, log=print):
    """Fetch the library's benchmark lap times (references/benchmarks/laps.json). True if they changed here."""
    import urllib.error
    path = path or BENCH_PATH
    try:
        raw = _library_get((base or LIBRARY_URL) + "benchmarks/laps.json", timeout, limit=1_000_000)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        return False
    prob = bench_problem(json.loads(raw.decode("utf-8")))
    if prob:
        log(f"Library benchmarks not used: {prob}")
        return False
    try:
        with open(path, "rb") as fh:
            if fh.read() == raw:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "wb") as fh:
        fh.write(raw)
    os.replace(path + ".tmp", path)
    benchmarks_changed()
    return True


def sync_library_tracks(seen, track_dir=None, timeout=8.0, api=None, log=print):
    """Bring the library's starter-lap track shapes (references/tracks/) into TRACK_DIR: new and changed files
    are downloaded, files taken out of the library are removed. Returns the names of the tracks added or updated."""
    import urllib.error
    store = track_dir or TRACK_DIR
    try:
        listing = list_library(timeout, (api or LIBRARY_API) + "/tracks")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        listing = []
    names = {it["name"] for it in listing}
    changed = []
    for name in [n for n in seen if n not in names]:
        del seen[name]
        try:
            os.remove(os.path.join(store, name))
            changed.append(name)
        except OSError:
            pass
    got = []
    for it in listing:
        name = it["name"]
        if seen.get(name) == it["sha"] or not it["url"] or it["size"] > 200_000 \
                or not re.fullmatch(r"[A-Za-z0-9]{2,40}\.json", name):
            continue
        try:
            raw = _library_get(it["url"], timeout, limit=200_000)
            d = json.loads(raw.decode("utf-8"))
            prob = track_file_problem(d)
            if prob or d["id"] + ".json" != name:
                raise ValueError(prob or "id doesn't match the file name")
            if d["id"] in STARTER_TRACKS:           # built in already
                seen[name] = it["sha"]
                continue
            os.makedirs(store, exist_ok=True)
            with open(os.path.join(store, name + ".tmp"), "wb") as fh:
                fh.write(raw)
            os.replace(os.path.join(store, name + ".tmp"), os.path.join(store, name))
            got.append(d["spoken"])
        except Exception as e:
            log(f"Library track {name} not used: {e}")
        seen[name] = it["sha"]
    if got or changed:
        starter_tracks_changed()
    return got


def sync_library(coach, seen, store_dir=None, timeout=8.0, api=None, log=print):
    """Bring the shared library's laps into the reference folder: new combinations are added, library laps that
    changed in the library are updated, and library laps taken out of the library are removed. The driver's own
    laps are never touched. seen ({file name: sha}) is
    updated in place, so unchanged files aren't downloaded again. Returns (added, updated) lists of keys.
    A lap for the combination being driven is adopted straight away if the coach isn't on the driver's own lap."""
    store = store_dir or coach.store_dir
    added, updated = [], []
    listing = list_library(timeout, api)
    in_library = {it["name"] for it in listing}
    for name in [n for n in seen if n not in in_library]:
        # taken out of the library (e.g. a bad lap): drop the downloaded copy too, unless it's being driven
        del seen[name]
        dest = os.path.join(store, name)
        try:
            with open(dest, encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("source") == "library" and (coach is None or coach.key != tuple(d.get("key") or ())):
                os.remove(dest)
                log(f"Library lap removed (no longer in the library): {name}")
        except Exception:
            pass
    for it in listing:
        name = it["name"]
        if seen.get(name) == it["sha"] or not it["url"] or it["size"] > 3_000_000:
            continue
        dest = os.path.join(store, name)
        local_src = None
        if os.path.exists(dest):
            try:
                with open(dest, encoding="utf-8") as fh:
                    local_src = json.load(fh).get("source") or "own"
            except Exception:
                local_src = "own"           # unreadable: leave it alone
        if local_src not in (None, "library"):
            seen[name] = it["sha"]          # the driver's own lap for this combination: never replaced
            continue
        try:
            d = _checked_library_lap(_library_get(it["url"], timeout), name)
        except Exception as e:
            log(f"Library lap {name} not used: {e}")
            seen[name] = it["sha"]
            continue
        key = tuple(d["key"])
        if coach is not None and coach.key == key and coach.ref_source == "own":
            seen[name] = it["sha"]
            continue
        try:
            adopted = coach.import_reference(d, dest) if coach is not None else False
            if coach is None:
                os.makedirs(store, exist_ok=True)
                with open(dest, "w", encoding="utf-8") as fh:
                    json.dump(d, fh)
        except Exception as e:
            log(f"Library lap {name} not saved: {e}")
            continue
        seen[name] = it["sha"]
        (updated if local_src == "library" else added).append(key)
        if adopted:
            coach.say(f"A new reference lap for this car and track just arrived from the SimCoach library, "
                      f"{fmt_time(coach.best_time)}. I'll coach you against it.", time.monotonic(), force=True)
    return added, updated


# ---- sharing best laps from the app (GitHub sign-in with a one-time code, then a commit or a pull request) ----
GITHUB_API = "https://api.github.com"
GITHUB_WEB = "https://github.com"
# The SimCoach OAuth app's client ID (public, not a secret: it only names the app on GitHub's sign-in page).
GITHUB_CLIENT_ID = "Ov23litlosIIZII412tg"
BEST_DIR = os.path.join(REPORT_DIR, "Best laps")


def share_payload(d):
    """The exact bytes a lap is shared as: the reference marked as a library lap, compact JSON. The same lap always
    gives the same bytes, so its git fingerprint tells whether the library already has it."""
    out = dict(d)
    out["source"] = "library"
    out["provisional"] = False
    return json.dumps(out, separators=(",", ":"), sort_keys=True).encode("utf-8")


def git_blob_sha(data):
    import hashlib
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def shareable_lap(path):
    """The driver's own clean lap in a reference file, or None (library laps, provisional laps, unusable files)."""
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return None
    if ref_problem(d) or d.get("provisional") or d.get("source") in ("library", "starter"):
        return None
    return d


def save_best_laps(ref_dir, best_dir):
    """Keep the Best laps folder in step with the driver's own reference laps: one ready-to-share file per sim /
    track / car, rewritten when the lap improves. Returns the file names written."""
    written = []
    try:
        names = sorted(f for f in os.listdir(ref_dir) if f.endswith(".json") and not f.endswith(".sessions.json"))
    except OSError:
        return written
    for name in names:
        d = shareable_lap(os.path.join(ref_dir, name))
        if d is None:
            continue
        data = share_payload(d)
        dest = os.path.join(best_dir, name)
        try:
            with open(dest, "rb") as fh:
                if fh.read() == data:
                    continue
        except OSError:
            pass
        try:
            os.makedirs(best_dir, exist_ok=True)
            with open(dest + ".tmp", "wb") as fh:
                fh.write(data)
            os.replace(dest + ".tmp", dest)
            written.append(name)
        except OSError:
            continue
    return written


def library_submission_problem(d, name, current=None):
    """None if d can go into the shared library as file `name`, else why not. The same rules run in the app
    (before sending) and on GitHub (tools/references/review_submission.py, before adding it): a complete, clean
    lap for the sim / track / car in the file name, believable numbers, and faster than the library's lap for
    that combination (current), if it has one."""
    prob = ref_problem(d)
    if prob:
        return f"not a usable lap ({prob})"
    if library_file_name(d["key"]) != name:
        return "the file name doesn't match its sim, track and car"
    if d.get("provisional") or d.get("source") == "starter":
        return "not a clean lap"
    bt = float(d["best_time"])
    ref = d["ref"]
    t, spd = ref["t"], ref["speed"]
    if not 15.0 <= bt <= 1800.0:
        return "lap time out of range"
    if not (min(spd) >= 0 and max(spd) <= 500):
        return "speed trace out of range"
    if t[0] > 5.0 or not (0.8 * bt <= t[-1] <= bt + 2.0):
        return "the lap trace doesn't match the lap time"
    if sum(1 for a, b in zip(t, t[1:]) if b < a - 0.05) > BINS // 100:
        return "the lap trace runs backwards"
    if current is not None:
        try:
            cur = float(current.get("best_time") or 0)
        except (TypeError, ValueError):
            cur = 0
        if cur > 0 and bt >= cur - 0.0005:
            return f"the library's lap is faster or equal ({fmt_time(cur).replace(' ', ':')})"
    return None


def share_laps(best_dir, names, token, log=print):
    """Upload these Best laps files to the library. Returns ({name: {"sha", "status", "url", "time", "when"}},
    [(name, error text, http status)]). Stops at the first sign-in failure."""
    results, errors = {}, []
    for name in names:
        try:
            with open(os.path.join(best_dir, name), "rb") as fh:
                data = fh.read()
            d = json.loads(data.decode("utf-8"))
            k = d["key"]
            title = f"Best lap: {k[0]} · {k[1]} · {k[2]} · {fmt_time(d.get('best_time') or 0)}"
            kind, url = upload_library_lap(token, name, data, title, log=log)
            results[name] = {"sha": git_blob_sha(data), "status": kind, "url": url, "time": d.get("best_time"),
                             "when": time.strftime("%Y-%m-%d %H:%M")}
        except GitHubError as e:
            errors.append((name, str(e), e.status))
            if e.status == 401:
                break
        except Exception as e:
            errors.append((name, f"{type(e).__name__}: {e}", 0))
    return results, errors


def laps_to_auto_share(best_dir, ref_dir, shared):
    """Best laps that haven't been sent to the library in their current form: new laps and laps improved since
    they were last sent. A lap the library already turned down isn't sent again until it gets faster."""
    out = []
    try:
        names = sorted(f for f in os.listdir(best_dir) if f.endswith(".json"))
    except OSError:
        return out
    for name in names:
        if not os.path.exists(os.path.join(ref_dir, name)):
            continue
        try:
            with open(os.path.join(best_dir, name), "rb") as fh:
                sha = git_blob_sha(fh.read())
        except OSError:
            continue
        if (shared.get(name) or {}).get("sha") != sha:
            out.append(name)
    return out


class GitHubError(Exception):
    def __init__(self, msg, status=0):
        super().__init__(msg)
        self.status = status


def _gh_call(method, url, token=None, body=None, form=None, timeout=20.0):
    import urllib.error
    import urllib.request
    from urllib.parse import urlencode
    headers = {"User-Agent": f"SimCoach/{APP_VERSION}", "Accept": "application/vnd.github+json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if form is not None:
        data = urlencode(form).encode()
        headers["Accept"] = "application/json"
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8"))
            msg = err.get("message") or err.get("error_description") or err.get("error") or e.reason
        except Exception:
            msg = e.reason
        raise GitHubError(f"GitHub said: {msg} ({e.code})", e.code) from None
    return json.loads(raw.decode("utf-8")) if raw.strip() else {}


def github_device_start(client_id):
    """Start a sign-in: {"user_code", "verification_uri", "device_code", "interval", "expires_in"}."""
    d = _gh_call("POST", f"{GITHUB_WEB}/login/device/code", form={"client_id": client_id, "scope": "public_repo"})
    if not d.get("user_code") or not d.get("device_code"):
        raise GitHubError(d.get("error_description") or d.get("error") or "GitHub didn't give a sign-in code")
    return d


def github_device_poll(client_id, start, cancelled=lambda: False, sleep=time.sleep):
    """Wait for the driver to enter the code on GitHub; returns the access token (raises on denial or expiry)."""
    interval = max(1, int(start.get("interval") or 5))
    deadline = time.monotonic() + int(start.get("expires_in") or 900)
    while time.monotonic() < deadline and not cancelled():
        sleep(interval)
        d = _gh_call("POST", f"{GITHUB_WEB}/login/oauth/access_token",
                     form={"client_id": client_id, "device_code": start["device_code"],
                           "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if d.get("access_token"):
            return d["access_token"]
        err = d.get("error")
        if err == "slow_down":
            interval += 5
        elif err != "authorization_pending":
            raise GitHubError({"access_denied": "sign-in was cancelled on GitHub",
                               "expired_token": "the code expired"}.get(err, d.get("error_description") or err))
    raise GitHubError("sign-in timed out" if not cancelled() else "sign-in cancelled")


def upload_library_lap(token, name, data, title, repo=None, log=print):
    """Put one lap in the shared library. With write access to the library's repository it's committed straight
    in; otherwise it goes to the driver's own copy (fork) of it and a pull request asks the owner to add it.
    Proposals are checked and added automatically on GitHub (the same rules as here).
    Returns ("added" | "proposed", web link) or ("refused", why) when it can't go in (e.g. the library is faster)."""
    import base64
    repo = repo or UPDATE_REPO
    api = GITHUB_API
    me = _gh_call("GET", f"{api}/user", token)["login"]
    info = _gh_call("GET", f"{api}/repos/{repo}", token)
    base = info.get("default_branch") or "main"
    path = f"references/{name}"
    try:
        cur = _gh_call("GET", f"{api}/repos/{repo}/contents/{path}?ref={base}", token)
        existing = cur.get("sha")
    except GitHubError as e:
        if e.status != 404:
            raise
        cur, existing = {}, None
    if existing == git_blob_sha(data):
        return "added", f"{GITHUB_WEB}/{repo}/blob/{base}/{path}"
    current = None
    if existing:
        try:
            import base64 as _b64
            current = json.loads(_b64.b64decode(cur.get("content") or "").decode("utf-8"))
        except Exception:
            current = None
    prob = library_submission_problem(json.loads(data.decode("utf-8")), name, current)
    if prob:
        return "refused", prob
    put = {"message": title, "content": base64.b64encode(data).decode("ascii")}
    if existing:
        put["sha"] = existing
    if (info.get("permissions") or {}).get("push"):
        put["branch"] = base
        r = _gh_call("PUT", f"{api}/repos/{repo}/contents/{path}", token, put)
        return "added", (r.get("content") or {}).get("html_url") or f"{GITHUB_WEB}/{repo}/blob/{base}/{path}"
    fork = _gh_call("POST", f"{api}/repos/{repo}/forks", token, {}).get("full_name") or f"{me}/{repo.split('/')[1]}"
    for _ in range(30):                              # a new fork takes a few seconds to appear
        try:
            _gh_call("GET", f"{api}/repos/{fork}", token)
            break
        except GitHubError as e:
            if e.status != 404:
                raise
            time.sleep(2)
    try:                                             # an older fork: bring it up to date with the library first
        _gh_call("POST", f"{api}/repos/{fork}/merge-upstream", token, {"branch": base})
    except GitHubError:
        pass
    head = _gh_call("GET", f"{api}/repos/{repo}/git/ref/heads/{base}", token)["object"]["sha"]
    branch = "lap-" + re.sub(r"[^A-Za-z0-9-]+", "-", name[:-5]).strip("-")[:60] + time.strftime("-%Y%m%d%H%M%S")
    try:
        _gh_call("POST", f"{api}/repos/{fork}/git/refs", token, {"ref": f"refs/heads/{branch}", "sha": head})
    except GitHubError as e:
        if e.status != 422:
            raise
        # the fork doesn't have the library's newest commit: branch from the fork's own copy instead
        head = _gh_call("GET", f"{api}/repos/{fork}/git/ref/heads/{base}", token)["object"]["sha"]
        _gh_call("POST", f"{api}/repos/{fork}/git/refs", token, {"ref": f"refs/heads/{branch}", "sha": head})
    put["branch"] = branch
    try:
        mine = _gh_call("GET", f"{api}/repos/{fork}/contents/{path}?ref={branch}", token).get("sha")
    except GitHubError as e:
        if e.status != 404:
            raise
        mine = None
    put.pop("sha", None)
    if mine:
        put["sha"] = mine
    _gh_call("PUT", f"{api}/repos/{fork}/contents/{path}", token, put)
    pr = _gh_call("POST", f"{api}/repos/{repo}/pulls", token,
                  {"title": title, "head": f"{me}:{branch}", "base": base,
                   "body": "Shared from SimCoach's Best laps tab. It's checked and added to the library "
                           "automatically (tools/references/review_submission.py)."})
    log(f"Proposed {name} for the library: {pr.get('html_url')}")
    return "proposed", pr.get("html_url") or f"{GITHUB_WEB}/{repo}/pulls"


def installed_copy():
    """True when this is the copy SimCoach-Setup.exe installed (so the installer can update it in place)."""
    local = os.environ.get("LOCALAPPDATA") or ""
    return bool(local) and os.path.normcase(SCRIPT_DIR) == os.path.normcase(os.path.join(local, "Programs", "SimCoach"))


def download_installer(url, dest, progress=None, timeout=30.0):
    """Download the installer to dest and check it really is a Windows program (not an error page)."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": f"SimCoach/{APP_VERSION}"})
    tmp = dest + ".part"
    got = 0
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as fh:
        total = int(r.headers.get("Content-Length") or 0)
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)
    with open(tmp, "rb") as fh:
        head = fh.read(2)
    if head != b"MZ" or got < 500_000 or (total and got != total):
        os.remove(tmp)
        raise ValueError("the download wasn't a complete SimCoach installer")
    os.replace(tmp, dest)
    return dest


# --- second screen: a read-only live page for a phone or tablet on the same network --------------------------
SECOND_SCREEN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>SimCoach live</title>
<style>
:root{--bg:#0b0f14;--panel:#121821;--line:#263142;--fg:#e6edf3;--mut:#8d99a8;--good:#34d399;--bad:#f87171;--tip:#fcd34d;--acc:#3d8bfd}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.35 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
padding:12px 16px env(safe-area-inset-bottom)}header{display:flex;justify-content:space-between;align-items:baseline;gap:8px;color:var(--mut);font-size:13px}
#delta{font:700 clamp(64px,22vw,180px)/1 ui-monospace,Menlo,Consolas,monospace;text-align:center;margin:10px 0 4px;letter-spacing:-2px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-top:8px}
.k{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}.k span{display:block;color:var(--mut);font-size:12px}
.k b{font-size:22px;font-variant-numeric:tabular-nums}.k small{display:block;color:var(--mut);font-size:13px}.msg{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;margin-top:8px}
.msg span{color:var(--mut);font-size:12px;display:block}#focus{color:var(--tip)}#off{color:var(--mut);text-align:center;margin-top:30px}
</style></head><body>
<header><b id="title">SimCoach</b><span id="status">connecting…</span></header>
<div id="delta">--.--</div>
<div class="grid">
<div class="k"><span>Lap</span><b id="lap">–</b></div><div class="k"><span>Last</span><b id="last">–</b></div>
<div class="k"><span>Best</span><b id="best">–</b></div><div class="k"><span>Position</span><b id="pos">–</b></div>
<div class="k"><span>Gap ahead</span><b id="ga">–</b></div><div class="k"><span>Gap behind</span><b id="gb">–</b></div>
<div class="k"><span>Fuel</span><b id="fuel">–</b><small id="fuellaps"></small></div><div class="k"><span>Speed · gear</span><b id="spd">–</b></div>
</div>
<div class="msg"><span>Focus</span><div id="focus">–</div></div>
<div class="msg"><span>Coach</span><div id="coach">–</div></div>
<script>
const $=id=>document.getElementById(id);let fails=0;
async function tick(){try{const r=await fetch('data.json',{cache:'no-store'});const d=await r.json();fails=0;
$('title').textContent=d.track?`${d.track} · ${d.car}`:'SimCoach '+d.version;
$('status').textContent=d.live?(d.sim||'live'):'waiting for a sim';
$('delta').textContent=d.delta||'--.--';$('delta').style.color=d.delta_color||'';
$('lap').textContent=d.lap??'–';$('last').textContent=d.last||'–';$('best').textContent=d.best||'–';
$('pos').textContent=d.pos?('P'+d.pos+(d.cars?' / '+d.cars:'')):'–';
$('ga').textContent=d.gap_ahead!=null?d.gap_ahead.toFixed(1)+' s':'–';$('gb').textContent=d.gap_behind!=null?d.gap_behind.toFixed(1)+' s':'–';
$('fuel').textContent=d.fuel??'–';$('fuellaps').textContent=d.fuel_laps!=null?'about '+d.fuel_laps+' laps left':'';
$('spd').textContent=d.speed!=null?d.speed+' · '+(d.gear>0?d.gear:d.gear==0?'N':'R'):'–';
$('focus').textContent=d.focus||'–';$('coach').textContent=d.coach||'–';}
catch(e){if(++fails>3)$('status').textContent='SimCoach not reachable';}}
setInterval(tick,250);tick();
</script></body></html>"""


def lan_ip():
    """This PC's address on the local network (no packets are sent)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def other_lan_ips():
    """This PC's other private IPv4 addresses (a second adapter, a VPN): tried when the main one doesn't work."""
    import ipaddress
    import socket
    main, out = lan_ip(), []
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            a = ipaddress.ip_address(ip)
            if ip != main and a.is_private and not a.is_loopback and not a.is_link_local and ip not in out:
                out.append(ip)
    except Exception:
        pass
    return out[:3]


class SecondScreen:
    """Serves SECOND_SCREEN_HTML and a JSON snapshot. Read-only: nothing on the page can change SimCoach."""

    def __init__(self, snapshot, log=print, token=""):
        self.snapshot, self.log = snapshot, log
        self.httpd, self.port = None, None
        self.token = token or "live"     # secret part of the address: only people you give the link to can open it

    def running(self):
        return self.httpd is not None

    def url(self):
        return f"http://{lan_ip()}:{self.port}/{self.token}/" if self.port else ""

    def start(self, port, host="0.0.0.0"):
        if self.httpd is not None and self.port == port:
            return True
        self.stop()
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        snap, page, base = self.snapshot, SECOND_SCREEN_HTML.encode("utf-8"), f"/{self.token}/"

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path in (base, base + "index.html"):
                    body, ctype = page, "text/html; charset=utf-8"
                elif path == base + "data.json":
                    try:
                        body = json.dumps(snap(), separators=(",", ":")).encode("utf-8")
                    except Exception as e:
                        body = json.dumps({"error": str(e)}).encode("utf-8")
                    ctype = "application/json"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        try:
            httpd = ThreadingHTTPServer((host, int(port)), H)
        except OSError as e:
            self.log(f"Phone screen couldn't start on port {port}: {e}")
            return False
        httpd.daemon_threads = True
        self.httpd, self.port = httpd, int(port)
        threading.Thread(target=httpd.serve_forever, daemon=True, name="second-screen").start()
        self.log(f"Phone screen on: open {self.url()} on a phone or tablet on the same Wi-Fi.")
        return True

    def stop(self):
        h, self.httpd, self.port = self.httpd, None, None
        if h is not None:
            try:
                h.shutdown()
                h.server_close()
            except Exception:
                pass


class App:
    """Main window. Also implements post(**kw) so the Coach can push live updates to it."""

    def __init__(self, cfg, voice_on=True, mic_on=True):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.cfg = tk, ttk, cfg
        self.mic_on = mic_on
        self.inbox: "queue.Queue[dict]" = queue.Queue()
        self.logq: "queue.Queue[str]" = queue.Queue()
        self.running = False
        self.stop = None
        self.readers = None
        self._readers_stale = False
        self.listener = None
        self.overlay_win = None
        self._font_fams = None
        self._last_mic_ui = None
        self._last_table_rev = None

        r = self.root = tk.Tk()
        r.title(f"SimCoach {APP_VERSION}")
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        ww, wh = min(1340, max(800, sw - 40)), min(900, max(560, sh - 90))
        r.geometry(f"{ww}x{wh}")
        r.minsize(min(1080, ww), min(820, wh))
        r.configure(bg=C["bg"])
        self._set_icon()
        self._style()

        self.voice = Voice(cfg, enabled=voice_on, log=self.log)
        self.controls = Controls(cfg, log=self.log)
        self.coach = Coach(cfg, self.voice, self, REF_DIR, log=self.log)
        self.coach.crew = Crew(cfg, self.voice, self, log=self.log, coach=self.coach)
        self.conv = Conversation(cfg, self.coach, self.voice, self, log=self.log)
        self.voice.events = self.post
        self.talk_pref = int(cfg.get("talk_level", 1))
        self._rc = {"release": None, "await_voice": False}
        self.controls.on("repeat", self._btn_repeat)
        self.controls.on("mute", self._btn_mute)
        self.controls.on("tones", self._btn_tones)
        self.controls.on("overlay", lambda: self.post(ov_cmd="toggle"))
        self.controls.on("capture", self._btn_capture)
        self.controls.on("sheet", lambda: self.post(setup_toggle=True))
        self.sheet_win = None
        if cfg.get("csp_weather_app", True):
            threading.Thread(target=install_csp_weather_app, args=(self.log,), daemon=True, name="csp-app").start()
        if CAPTURE_AT_START:
            self.log(self.coach.capture.arm(CAPTURE_AT_START))

        self._layout()
        _win_dark_titlebar(r)
        r.protocol("WM_DELETE_WINDOW", self.quit)
        r.after(100, self._pump)
        r.after(1000, self._refresh_tables)
        if cfg.get("auto_start"):
            r.after(800, self.start_coach)
        if not self.cfg.get("second_screen_token"):
            import secrets
            self.cfg["second_screen_token"] = secrets.token_urlsafe(9)
            save_config(self.cfg)
        self.screen = SecondScreen(self._screen_data, self.log, self.cfg["second_screen_token"])
        self.update_info = None
        r.after(6000, self._update_tick)
        r.after(15000, self._library_tick)
        r.after(300, self._apply_second_screen)
        if not cfg.get("driver_name") and not cfg.get("name_asked"):
            r.after(400, self._ask_name)

    def _ask_name(self):
        """First launch (or Settings > Quick setup): three short steps so the coach can be heard and talked to:
        the driver's name, where the voice plays (with a test call), and the push-to-talk wheel button."""
        if getattr(self, "_setup_win", None) is not None:
            try:
                self._setup_win.lift()
                return
            except Exception:
                self._setup_win = None
        tk, ttk = self.tk, self.ttk
        w = self._setup_win = tk.Toplevel(self.root)
        w.title("Welcome to SimCoach")
        w.configure(bg=C["panel"])
        w.resizable(False, False)
        w.transient(self.root)
        f = ttk.Frame(w, style="Card.TFrame", padding=18)
        f.pack(fill="both", expand=True)
        step_lbl = ttk.Label(f, text="", style="Mut.TLabel")
        step_lbl.pack(anchor="w")
        title = ttk.Label(f, text="", style="Card.TLabel", font=self._font(12, True))
        title.pack(anchor="w", pady=(2, 0))
        note = ttk.Label(f, text="", style="Mut.TLabel", wraplength=400, justify="left")
        note.pack(anchor="w", pady=(4, 10))
        body = ttk.Frame(f, style="Card.TFrame")
        body.pack(fill="x")
        b = ttk.Frame(f, style="Card.TFrame")
        b.pack(fill="x", pady=(14, 0))
        next_btn = ttk.Button(b, text="Next", style="Accent.TButton")
        next_btn.pack(side="right")
        skip_btn = ttk.Button(b, text="Skip setup")
        skip_btn.pack(side="right", padx=8)
        name = tk.StringVar(value=self.cfg.get("driver_name") or "")
        state = {"step": 0, "poll": None}

        def close():
            if state["poll"]:
                try:
                    w.after_cancel(state["poll"])
                except Exception:
                    pass
            self.cfg["name_asked"] = True
            save_config(self.cfg)
            self._setup_win = None
            w.destroy()

        def save_name():
            n = name.get().strip()[:40]
            self.cfg["name_asked"] = True
            if n and n != self.cfg.get("driver_name"):
                self.cfg["driver_name"] = n
                if "driver_name" in getattr(self, "vars", {}):
                    self.vars["driver_name"].set(n)
                self.log(f"Driver name set to {n}.")
            save_config(self.cfg)

        def show(step):
            state["step"] = step
            for c in body.winfo_children():
                c.destroy()
            step_lbl.configure(text=f"Step {step + 1} of 3")
            w.unbind("<Return>")
            if step == 0:
                title.configure(text="What should your crew call you?")
                note.configure(text="Your coach, engineer and spotter use it on the radio. You can change it in Settings.")
                ent = ttk.Entry(body, textvariable=name, width=32)
                ent.pack(anchor="w", fill="x")
                ent.bind("<Return>", lambda _e: go_next())
                ent.focus_set()
                next_btn.configure(text="Next")
            elif step == 1:
                title.configure(text="Where should you hear the coach?")
                note.configure(text="Pick your headset or speakers (a VR headset shows up here too), then play a test "
                                    "call. Nothing heard? Pick another and try again.")
                var = self.vars["audio_out"]
                ttk.Combobox(body, textvariable=var, values=list(self.out_combo.cget("values")) or [var.get()],
                             state="readonly", width=40).pack(anchor="w")
                ttk.Button(body, text="Play test call", command=self.test_voice).pack(anchor="w", pady=(10, 0))
                next_btn.configure(text="Next")
            else:
                title.configure(text="Talk to your crew")
                note.configure(text="Hold a button on your wheel to talk, like a real radio: ask for the gap, your fuel, "
                                    "a setup change, or say \u201cwork on turn 3\u201d. Click Set, then press the button "
                                    "you want. No wheel? Hold F8, or the Hold to talk button on the Live tab.")
                row = ttk.Frame(body, style="Card.TFrame")
                row.pack(anchor="w")
                ttk.Button(row, text="Set wheel button", command=lambda: self.bind_action("ptt")).pack(side="left")
                ptt = ttk.Label(row, text="", style="Card.TLabel")
                ptt.pack(side="left", padx=10)

                def poll():
                    try:
                        ptt.configure(text=self.bind_lbls["ptt"].cget("text"))
                        state["poll"] = w.after(300, poll)
                    except Exception:
                        state["poll"] = None
                poll()
                ttk.Label(body, text="You're set. Press Start coaching, then go on track in any supported sim.",
                          style="Card.TLabel", wraplength=400, justify="left").pack(anchor="w", pady=(12, 0))
                next_btn.configure(text="Finish")
                skip_btn.pack_forget()

        def go_next():
            step = state["step"]
            if step == 0:
                save_name()
            elif step == 1:
                self.save_settings(quiet=True)
            if step >= 2:
                close()
            else:
                show(step + 1)
        next_btn.configure(command=go_next)
        skip_btn.configure(command=close)
        w.protocol("WM_DELETE_WINDOW", close)
        _win_dark_titlebar(w)
        show(0)
        w.update_idletasks()
        try:
            x = self.root.winfo_rootx() + (self.root.winfo_width() - w.winfo_reqwidth()) // 2
            y = self.root.winfo_rooty() + 120
            w.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    def _set_icon(self):
        try:
            self._icon_img = self.tk.PhotoImage(data="".join(_ICON_PNG))
            self.root.iconphoto(True, self._icon_img)
        except Exception:
            self._icon_img = None
        ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SimCoach.ico")
        if sys.platform == "win32" and os.path.exists(ico):
            try:
                self.root.iconbitmap(default=ico)
            except Exception:
                pass

    def _font(self, size, bold=False, mono=False):
        if self._font_fams is None:
            import tkinter.font as tkfont
            fams = set(tkfont.families(self.root))
            ui_fam = next((f for f in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica", "DejaVu Sans",
                                       "Arial") if f in fams), "TkDefaultFont")
            head_fam = next((f for f in ("Segoe UI Variable Display", "Segoe UI Semibold", ui_fam) if f in fams), ui_fam)
            mono_fam = next((f for f in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New") if f in fams),
                            "TkDefaultFont")
            self._font_fams = (ui_fam, mono_fam, head_fam)
        fam = self._font_fams[1] if mono else self._font_fams[2] if (bold and size >= 14) else self._font_fams[0]
        return (fam, size, "bold") if bold else (fam, size)

    def _style(self):
        """Flat, modern, always-dark ttk theme (clam base)."""
        st = self.ttk.Style(self.root)
        st.theme_use("clam")
        f10 = self._font(10)
        st.configure(".", background=C["bg"], foreground=C["fg"], fieldbackground=C["panel2"], font=f10,
                     bordercolor=C["line"], lightcolor=C["line"], darkcolor=C["line"], troughcolor=C["panel"],
                     focuscolor=C["acc"], selectbackground=C["acc"], selectforeground=C["acc_fg"],
                     insertcolor=C["fg"])
        st.configure("TFrame", background=C["bg"])
        st.configure("Card.TFrame", background=C["panel"], borderwidth=0)
        st.configure("CardBox.TFrame", background=C["panel"], bordercolor=C["line"], lightcolor=C["line"],
                     darkcolor=C["line"], borderwidth=1, relief="solid")
        st.configure("Bar.TFrame", background=C["bg"])
        st.configure("Pill.TFrame", background=C["panel2"])
        st.configure("TLabel", background=C["bg"], foreground=C["fg"])
        st.configure("Card.TLabel", background=C["panel"])
        st.configure("Mut.TLabel", background=C["panel"], foreground=C["mut"])
        st.configure("BgMut.TLabel", background=C["bg"], foreground=C["mut"], font=self._font(9))
        st.configure("Pill.TLabel", background=C["panel2"], foreground=C["fg"], font=self._font(9, True))
        st.configure("Sec.TLabel", background=C["panel"], foreground=C["fg"], font=self._font(11, True))
        st.configure("H.TLabel", background=C["bg"], font=self._font(17, True))
        st.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(0, 4, 0, 0),
                     bordercolor=C["bg"], lightcolor=C["bg"], darkcolor=C["bg"])
        st.configure("TNotebook.Tab", background=C["bg"], foreground=C["mut"], padding=(18, 9), borderwidth=0,
                     font=self._font(10, True), bordercolor=C["bg"], lightcolor=C["bg"], darkcolor=C["bg"])
        st.map("TNotebook.Tab", background=[("selected", C["panel2"]), ("active", C["hover"])],
               foreground=[("selected", C["fg"]), ("active", C["fg"])],
               lightcolor=[("selected", C["acc"])], bordercolor=[("selected", C["panel2"])],
               darkcolor=[("selected", C["panel2"])], expand=[("selected", (0, 0, 0, 0))])
        try:
            st.layout("TNotebook.Tab", [("Notebook.tab", {"sticky": "nswe", "children": [
                ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                    ("Notebook.label", {"side": "top", "sticky": ""})]})]})])
        except Exception:
            pass
        st.configure("TButton", background=C["panel2"], foreground=C["fg"], padding=(14, 7), borderwidth=0,
                     relief="flat", focusthickness=0, lightcolor=C["panel2"], darkcolor=C["panel2"])
        st.map("TButton", background=[("pressed", C["line"]), ("active", C["hover"])],
               lightcolor=[("active", C["hover"])], darkcolor=[("active", C["hover"])])
        st.configure("Accent.TButton", background=C["acc"], foreground=C["acc_fg"], font=self._font(10, True),
                     lightcolor=C["acc"], darkcolor=C["acc"])
        st.map("Accent.TButton", background=[("pressed", "#2f6fd6"), ("active", C["acc_hi"])],
               lightcolor=[("active", C["acc_hi"])], darkcolor=[("active", C["acc_hi"])])
        st.configure("Stop.TButton", background="#ef4444", foreground="#ffffff", font=self._font(10, True),
                     lightcolor="#ef4444", darkcolor="#ef4444")
        st.map("Stop.TButton", background=[("pressed", "#b91c1c"), ("active", "#f05252")])
        st.configure("Small.TButton", padding=(10, 4))
        st.configure("Treeview", background=C["panel"], fieldbackground=C["panel"], foreground=C["fg"], rowheight=30,
                     borderwidth=0, relief="flat")
        st.configure("Treeview.Heading", background=C["panel2"], foreground=C["mut"], relief="flat", padding=(8, 6),
                     font=self._font(9, True), borderwidth=0)
        st.map("Treeview.Heading", background=[("active", C["hover"])])
        st.map("Treeview", background=[("selected", "#1d3557")], foreground=[("selected", C["fg"])])
        for w in ("TEntry", "TCombobox", "TSpinbox"):
            st.configure(w, fieldbackground=C["panel2"], foreground=C["fg"], insertcolor=C["fg"], padding=(8, 5),
                         bordercolor=C["line"], lightcolor=C["panel2"], darkcolor=C["panel2"], arrowcolor=C["mut"],
                         background=C["panel2"])
            st.map(w, bordercolor=[("focus", C["acc"])], lightcolor=[("focus", C["acc"])],
                   fieldbackground=[("readonly", C["panel2"])], foreground=[("readonly", C["fg"])],
                   selectbackground=[("readonly", C["panel2"])], selectforeground=[("readonly", C["fg"])],
                   arrowcolor=[("active", C["fg"])])
        self.root.option_add("*TCombobox*Listbox.background", C["panel2"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["acc"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", C["acc_fg"])
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)
        self.root.option_add("*Menu.background", C["panel2"])
        self.root.option_add("*Menu.foreground", C["fg"])
        self.root.option_add("*Menu.activeBackground", C["acc"])
        for o in ("Vertical", "Horizontal"):
            st.configure(f"{o}.TScrollbar", background=C["panel2"], troughcolor=C["panel"], bordercolor=C["panel"],
                         arrowcolor=C["mut"], lightcolor=C["panel2"], darkcolor=C["panel2"], relief="flat",
                         arrowsize=11, gripcount=0)
            st.map(f"{o}.TScrollbar", background=[("active", C["line"])])
        for w in ("TRadiobutton", "TCheckbutton"):
            st.configure(w, background=C["panel"], foreground=C["fg"], indicatorbackground=C["panel2"],
                         indicatorforeground=C["acc_fg"], indicatorrelief="flat", focusthickness=0)
            st.map(w, background=[("active", C["panel"])], foreground=[("active", C["fg"])],
                   indicatorbackground=[("selected", C["acc"]), ("active", C["hover"])])
        st.configure("Horizontal.TScale", background=C["acc"], troughcolor=C["panel2"], bordercolor=C["line"],
                     lightcolor=C["acc_hi"], darkcolor=C["acc"], sliderthickness=14, gripcount=0)
        st.map("Horizontal.TScale", background=[("active", C["acc_hi"])])

    def _flat_button(self, parent, text, **kw):
        """A flat accent tk.Button with hover (used where press/release events matter: hold to talk)."""
        b = self.tk.Button(parent, text=text, bg=C["acc"], fg=C["acc_fg"], activebackground=C["acc_hi"],
                           activeforeground=C["acc_fg"], relief="flat", bd=0, highlightthickness=0, cursor="hand2",
                           font=self._font(11, True), padx=20, pady=9, **kw)
        b.bind("<Enter>", lambda e: b.configure(bg=C["acc_hi"]))
        b.bind("<Leave>", lambda e: b.configure(bg=C["acc"]))
        return b

    def _scroll_area(self, parent):
        """A frame that scrolls vertically (mouse wheel or scrollbar) only when the window is too short for it."""
        tk, ttk = self.tk, self.ttk
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True, pady=(10, 0))
        cv = tk.Canvas(outer, bg=C["bg"], highlightthickness=0, bd=0, height=200)
        sb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(cv)
        win = cv.create_window(0, 0, window=inner, anchor="nw")

        def sync(_e=None):
            h = inner.winfo_reqheight()
            cv.configure(scrollregion=(0, 0, cv.winfo_width(), h))
            need = h > cv.winfo_height() + 2
            if need and not sb.winfo_ismapped():
                sb.pack(side="right", fill="y", before=cv)
            elif not need and sb.winfo_ismapped():
                sb.pack_forget()
                cv.yview_moveto(0)

        def resize(e):
            cv.itemconfigure(win, width=e.width)
            sync()

        def wheel(e):
            if not sb.winfo_ismapped() or not e.delta:
                return
            try:
                w = cv.winfo_containing(e.x_root, e.y_root)
            except Exception:
                return
            if w is not None and str(w).startswith(str(outer)):
                cv.yview_scroll(-1 if e.delta > 0 else 1, "units")

        inner.bind("<Configure>", sync)
        cv.bind("<Configure>", resize)
        cv.bind_all("<MouseWheel>", wheel, add="+")
        self._settings_canvas = cv
        return inner

    def _card(self, parent, **pack):
        f = self.ttk.Frame(parent, style="CardBox.TFrame", padding=16)
        f.pack(**pack)
        return f

    def _layout(self):
        tk, ttk = self.tk, self.ttk
        top = ttk.Frame(self.root, padding=(18, 14, 18, 6), style="Bar.TFrame")
        top.pack(fill="x")
        if self._icon_img is not None:
            try:
                self._logo = self._icon_img.subsample(2, 2)
                tk.Label(top, image=self._logo, bg=C["bg"], bd=0).pack(side="left", padx=(0, 10))
            except Exception:
                pass
        title = ttk.Frame(top, style="Bar.TFrame")
        title.pack(side="left")
        ttk.Label(title, text="SimCoach", style="H.TLabel").pack(anchor="w")
        ttk.Label(title, text=f"Race coach  ·  engineer  ·  strategist  ·  spotter  ·  v{APP_VERSION}",
                  style="BgMut.TLabel").pack(anchor="w")
        pill = ttk.Frame(top, style="Pill.TFrame", padding=(10, 5))
        pill.pack(side="left", padx=(22, 0))
        self.dot = tk.Canvas(pill, width=10, height=10, bg=C["panel2"], highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 7))
        self.dot_id = self.dot.create_oval(1, 1, 9, 9, fill=C["mut"], outline="")
        self.status_lbl = ttk.Label(pill, text="Not running", style="Pill.TLabel", foreground=C["mut"])
        self.status_lbl.pack(side="left")
        self.start_btn = ttk.Button(top, text="Start coaching", style="Accent.TButton", command=self.toggle)
        self.start_btn.pack(side="right")
        ttk.Button(top, text="Overlay", command=self.toggle_overlay).pack(side="right", padx=8)
        ttk.Button(top, text="Phone screen", command=self.phone_screen_dialog).pack(side="right")
        self.ov_lock_btn = ttk.Button(top, text="Unlock overlay" if self.cfg.get("overlay_locked") else "Lock overlay",
                                      command=self.toggle_overlay_lock)
        self.ov_lock_btn.pack(side="right")

        nb = self.nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=18, pady=(10, 18))
        tabs = [("Live", "tab_live"), ("Radio check", "tab_radio"), ("Laps & corners", "tab_laps"),
                ("Settings", "tab_set"), ("References", "tab_ref"), ("Best laps", "tab_best"), ("Reports", "tab_rep"),
                ("Log", "tab_log")]
        for name, attr in tabs:
            f = ttk.Frame(nb)
            setattr(self, attr, f)
            nb.add(f, text=name)
        self._live()
        self._radio()
        self._laps()
        self._settings()
        self._references()
        self._best_laps()
        self._reports()
        self._log()
        nb.bind("<<NotebookTabChanged>>", self._tab_changed)

    def _tab_changed(self, _e=None):
        tab = self.nb.select()
        if tab == str(self.tab_ref):
            self.load_refs()
        elif tab == str(self.tab_best):
            self.load_best()
        elif tab == str(self.tab_rep):
            self.load_reports()
        elif tab == str(self.tab_radio):
            self.ensure_listener()
        elif tab == str(self.tab_laps):
            self._refresh_tables_now(force=True)

    def _live(self):
        tk, ttk = self.tk, self.ttk
        t = self.tab_live
        head = self._card(t, fill="x", pady=(10, 8))
        self.head_lbl = ttk.Label(head, text="Press Start coaching, then go on track in any supported sim.", style="Mut.TLabel")
        self.head_lbl.pack(anchor="w")

        row = ttk.Frame(t)
        row.pack(fill="x")
        dcard = self._card(row, side="left", fill="both", expand=True, padx=(0, 8))
        ttk.Label(dcard, text="LIVE DELTA TO BEST", style="Mut.TLabel").pack(anchor="w")
        self.delta_lbl = tk.Label(dcard, text="--.--", bg=C["panel"], fg=C["fg"], font=self._font(54, True))
        self.delta_lbl.pack(anchor="w")
        kcard = self._card(row, side="left", fill="both", expand=True)
        self.kpi = {}
        for k, label in (("last", "Last lap"), ("best", "Best lap"), ("theo", "Theoretical best"), ("laps", "Laps"),
                         ("pace", "Pace vs target"), ("cons", "Consistency")):
            f = ttk.Frame(kcard, style="Card.TFrame")
            f.pack(fill="x", pady=3)
            ttk.Label(f, text=label, style="Mut.TLabel", width=18).pack(side="left")
            self.kpi[k] = ttk.Label(f, text="—", style="Card.TLabel", font=self._font(14, True))
            self.kpi[k].pack(side="left")

        tcard = self._card(t, fill="x", pady=8)
        ttk.Label(tcard, text="COACH", style="Mut.TLabel").pack(anchor="w")
        self.tip_lbl = tk.Label(tcard, text="—", bg=C["panel"], fg=C["tip"], font=self._font(15), wraplength=1040,
                                justify="left", anchor="w")
        self.tip_lbl.pack(fill="x", anchor="w")
        self.focus_lbl = tk.Label(tcard, text="", bg=C["panel"], fg=C["teal"], font=self._font(11), wraplength=1040,
                                  justify="left", anchor="w")
        self.focus_lbl.pack(fill="x", anchor="w", pady=(6, 0))
        self.heard_lbl = tk.Label(tcard, text="", bg=C["panel"], fg=C["violet"], font=self._font(10), anchor="w")
        self.heard_lbl.pack(fill="x", anchor="w", pady=(6, 0))

        ctl = self._card(t, fill="x")
        self.talk_btn = self._flat_button(ctl, "Hold to talk")
        self.talk_btn.pack(side="left")
        self.talk_btn.bind("<ButtonPress-1>", lambda e: self._ptt(True))
        self.talk_btn.bind("<ButtonRelease-1>", lambda e: self._ptt(False))
        ttk.Button(ctl, text="Test voice", command=self.test_voice).pack(side="left", padx=8)
        self.sheet_btn = ttk.Button(ctl, text="Setup sheet", command=self.show_setup_sheet)
        self.sheet_btn.pack(side="left")
        self.mute_var = tk.BooleanVar(value=self.cfg.get("talk_level", 1) == 0)
        ttk.Checkbutton(ctl, text="Quiet mode (answers only)", variable=self.mute_var,
                        command=self._mute_changed).pack(side="left", padx=8)
        self.mic_lbl = ttk.Label(ctl, text="Mic opens with coaching or the Radio check tab", style="Mut.TLabel")
        self.mic_lbl.pack(side="right")

    RC_STEPS = [("ptt", "Push-to-talk"), ("mic", "Microphone"), ("stt", "Speech recognition"),
                ("ai", "Coach answer"), ("voice", "Voice")]

    def _radio(self):
        """Talk to the engineer before launching a sim and see every step of the round trip."""
        tk, ttk = self.tk, self.ttk
        t = self.tab_radio
        head = self._card(t, fill="x", pady=(10, 8))
        ttk.Label(head, text="Radio check", style="Sec.TLabel").pack(anchor="w")
        ttk.Label(head, style="Mut.TLabel", wraplength=1040, justify="left",
                  text="Works without a sim. Hold your push-to-talk (wheel button, F8 or the button below), speak, "
                       "release. Each step turns green when it works. Try \u201cradio check\u201d (instant, no AI key needed), "
                       "then a real question like \u201cwhat should I focus on in my first session?\u201d (uses your AI provider).").pack(anchor="w", pady=(4, 0))
        steps = self._card(t, fill="x")
        self.rc_dots, self.rc_info = {}, {}
        for col, (k, label) in enumerate(self.RC_STEPS):
            f = ttk.Frame(steps, style="Card.TFrame")
            f.grid(row=0, column=col, sticky="nw", padx=(0, 18))
            hdr = ttk.Frame(f, style="Card.TFrame")
            hdr.pack(anchor="w")
            cv = tk.Canvas(hdr, width=12, height=12, bg=C["panel"], highlightthickness=0)
            cv.pack(side="left", padx=(0, 6))
            self.rc_dots[k] = (cv, cv.create_oval(1, 1, 11, 11, fill=C["mut"], outline=""))
            ttk.Label(hdr, text=label, style="Card.TLabel", font=self._font(10, True)).pack(side="left")
            self.rc_info[k] = ttk.Label(f, text="—", style="Mut.TLabel", wraplength=190, justify="left")
            self.rc_info[k].pack(anchor="w", pady=(4, 0))
        steps.grid_columnconfigure(len(self.RC_STEPS), weight=1)
        self.rc_meter = tk.Canvas(self.rc_info["mic"].master, width=200, height=14, bg=C["panel2"], highlightthickness=0)
        self.rc_meter.pack(anchor="w", pady=(6, 0))
        self.rc_bar = self.rc_meter.create_rectangle(0, 0, 0, 14, fill=C["good"], outline="")
        self.rc_info["ptt"].configure(text=self.controls.describe("ptt") + "\nor F8 / the button below")
        self.rc_info["ai"].configure(text=self._ai_status())

        chat = self._card(t, fill="both", expand=True, pady=8)
        top = ttk.Frame(chat, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="CONVERSATION", style="Mut.TLabel").pack(side="left")
        self.rc_rt = ttk.Label(top, text="", style="Mut.TLabel")
        self.rc_rt.pack(side="right")
        self.rc_txt = tk.Text(chat, bg=C["panel"], fg=C["fg"], insertbackground=C["fg"], relief="flat", bd=0, highlightthickness=0,
                              padx=8, pady=6, selectbackground=C["acc"], height=12,
                              font=self._font(11), wrap="word", state="disabled")
        self.rc_txt.pack(fill="both", expand=True, pady=(6, 0))
        self.rc_txt.tag_configure("you", foreground=C["violet"])
        self.rc_txt.tag_configure("eng", foreground=C["tip"])
        self.rc_txt.tag_configure("meta", foreground=C["mut"], font=self._font(9))
        self.rc_txt.tag_configure("bad", foreground=C["bad"])

        ctl = self._card(t, fill="x")
        self.rc_talk_btn = self._flat_button(ctl, "Hold to talk")
        self.rc_talk_btn.pack(side="left")
        self.rc_talk_btn.bind("<ButtonPress-1>", lambda e: self._ptt(True))
        self.rc_talk_btn.bind("<ButtonRelease-1>", lambda e: self._ptt(False))
        self.rc_entry = ttk.Entry(ctl, width=46)
        self.rc_entry.pack(side="left", padx=(12, 6))
        self.rc_entry.insert(0, "")
        self.rc_entry.bind("<Return>", lambda e: self._rc_send())
        ttk.Button(ctl, text="Send typed", command=self._rc_send).pack(side="left")
        ttk.Button(ctl, text="Clear", command=self._rc_clear).pack(side="left", padx=6)
        self.rc_state = ttk.Label(ctl, text="", style="Mut.TLabel")
        self.rc_state.pack(side="right")

    def _rc_line(self, who, text, tag, meta=""):
        w = self.rc_txt
        w.configure(state="normal")
        w.insert("end", f"{time.strftime('%H:%M:%S')}  ", "meta")
        w.insert("end", f"{who}: " if who else "", tag)
        w.insert("end", text, tag)
        if meta:
            w.insert("end", f"    {meta}", "meta")
        w.insert("end", "\n")
        w.see("end")
        w.configure(state="disabled")

    def _rc_set(self, step, state, info=None):
        cv, oid = self.rc_dots[step]
        cv.itemconfigure(oid, fill={"ok": C["good"], "busy": C["warn"], "bad": C["bad"], "idle": C["mut"]}[state])
        if info is not None:
            self.rc_info[step].configure(text=info)

    def _rc_clear(self):
        self.rc_txt.configure(state="normal")
        self.rc_txt.delete("1.0", "end")
        self.rc_txt.configure(state="disabled")
        for k, _ in self.RC_STEPS:
            self._rc_set(k, "idle")
        self.rc_rt.configure(text="")

    def _rc_send(self):
        text = self.rc_entry.get().strip()
        if not text:
            return
        self.rc_entry.delete(0, "end")
        self.save_settings(quiet=True)
        self._rc["release"], self._rc["await_voice"] = time.monotonic(), True
        self._rc_set("ptt", "idle", "(typed message)")
        self._rc_line("You (typed)", text, "you")
        threading.Thread(target=self.conv.handle, args=(text,), daemon=True, name="typed").start()

    def _rc_event(self, kw):
        """Radio-check updates from the listener, the conversation and the voice (all on the UI thread here)."""
        t = kw.get("rc_t", time.monotonic())
        if kw.get("rc_ptt") is True:
            self._rc_set("ptt", "ok", "Pressed ✓")
            self._rc_set("mic", "busy", "Listening…")
            for k in ("stt", "ai", "voice"):
                self._rc_set(k, "idle")
        elif kw.get("rc_ptt") is False:
            self._rc["release"], self._rc["await_voice"] = t, True
            self._rc_set("ptt", "ok", f"Held {kw.get('rc_clip_s', 0):.1f} s ✓")
        if "rc_fail" in kw:
            step, msg = kw["rc_fail"]
            self._rc_set(step, "bad", msg)
            self._rc_line("", msg, "bad")
            self._rc["await_voice"] = False
        if "rc_mic" in kw:
            self._rc_set("mic", "ok", f"Peak level {kw['rc_mic']}% ✓")
            self._rc_set("stt", "busy", "Recognising…")
        if "rc_heard" in kw:
            self._rc_set("stt", "ok", kw.get("rc_stt", "") + " ✓")
            self._rc_line("You", kw["rc_heard"], "you", kw.get("rc_stt", ""))
            self._rc_set("ai", "busy", "Thinking…")
        if "rc_thinking" in kw:
            self._rc_set("ai", "busy", f"Asking {AI_PROVIDERS[ai_provider(self.cfg)]['name']} {kw['rc_thinking']}…")
        if "rc_reply" in kw:
            fail = kw.get("rc_ai_fail")
            self._rc_set("ai", "bad" if fail else "ok", (fail or kw.get("rc_ai", "")) + ("" if fail else " ✓"))
            self._rc_line("Coach", self._pretty(kw["rc_reply"]), "bad" if fail else "eng", "" if fail else kw.get("rc_ai", ""))
            self._rc_set("voice", "busy", "Speaking…")
        if "rc_voice" in kw and self._rc["await_voice"]:
            engine, delay, kind, _text = kw["rc_voice"]
            if engine is None:
                self._rc_set("voice", "bad", "No audio output. Check Speaker / headset in Settings.")
            else:
                self._rc_set("voice", "ok", f"{engine} · started in {delay:.1f} s ✓")
                if self._rc["release"] is not None:
                    self.rc_rt.configure(text=f"Round trip {t - self._rc['release']:.1f} s  (release → coach talking)")
            self._rc["await_voice"] = False

    def _tree(self, parent, cols, widths, height=8):
        ttk = self.ttk
        f = ttk.Frame(parent, style="CardBox.TFrame", padding=1)
        f.pack(fill="both", expand=True, pady=(4, 10))
        tv = ttk.Treeview(f, columns=[c for c, _ in cols], show="headings", height=height)
        for (c, h), w in zip(cols, widths):
            tv.heading(c, text=h, anchor="w")
            tv.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(f, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return tv

    def _laps(self):
        ttk = self.ttk
        t = self.tab_laps
        ttk.Label(t, text="Laps this session").pack(anchor="w", pady=(10, 0))
        self.laps_tv = self._tree(t, [("n", "Lap"), ("time", "Time"), ("gap", "Gap to best")], (80, 160, 160))
        ttk.Label(t, text="Turn by turn (last lap vs your best)").pack(anchor="w")
        self.turns_tv = self._tree(t, [("turn", "Corner"), ("loss", "Last lap loss"), ("vmin", "Best min speed"),
                                       ("issue", "Latest issue")], (90, 120, 130, 600))

    def _settings(self):
        tk, ttk = self.tk, self.ttk
        t = self.tab_set
        foot = ttk.Frame(t)
        foot.pack(side="bottom", fill="x", pady=(10, 4))
        cols = self._scroll_area(t)
        # the right column always gets the width it asks for (its Set / Clear buttons and options must stay in
        # view); the left one takes the rest, where only the grey hints can run out of room
        right = ttk.Frame(cols)
        right.pack(side="right", fill="y")
        left = ttk.Frame(cols)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.vars = {}

        def grid_rows(card):
            g = ttk.Frame(card, style="Card.TFrame")
            g.pack(fill="x")
            return g

        def row(g, r, label, widget, hint=""):
            ttk.Label(g, text=label, style="Card.TLabel", width=17).grid(row=r, column=0, sticky="w", pady=5)
            widget.grid(row=r, column=1, sticky="w", pady=5)
            if hint:
                ttk.Label(g, text=hint, style="Mut.TLabel").grid(row=r, column=2, sticky="w", padx=8)

        a = self._card(left, fill="x", pady=(0, 8))
        ttk.Label(a, text="Voice & audio", style="Sec.TLabel").pack(anchor="w", pady=(0, 6))
        g = grid_rows(a)
        self.vars["driver_name"] = tk.StringVar(value=self.cfg.get("driver_name", ""))
        row(g, 0, "Your name", ttk.Entry(g, textvariable=self.vars["driver_name"], width=30))
        vnames = _VOICE_NAMES
        self.vars["voice"] = tk.StringVar(value=_LABEL_BY_VOICE.get(self.cfg.get("voice"), vnames[0]))
        row(g, 1, "Coach voice", ttk.Combobox(g, textvariable=self.vars["voice"], values=vnames, state="readonly", width=28))
        self.vars["speech_rate"] = tk.IntVar(value=int(self.cfg.get("speech_rate", 8)))
        row(g, 2, "Speaking speed", ttk.Scale(g, from_=-20, to=40, variable=self.vars["speech_rate"], length=200),
            "slower / faster")
        self.vars["volume"] = tk.DoubleVar(value=float(self.cfg.get("volume", 0.9)))
        row(g, 3, "Volume", ttk.Scale(g, from_=0.1, to=1.0, variable=self.vars["volume"], length=200))
        self.out_names = ["Windows default"]
        self.vars["audio_out"] = tk.StringVar(value=self.cfg.get("audio_out") or "Windows default")
        self.out_combo = ttk.Combobox(g, textvariable=self.vars["audio_out"], values=self.out_names, state="readonly", width=28)
        row(g, 4, "Speaker / headset", self.out_combo, "e.g. your VR headset")
        self.vars["mic"] = tk.StringVar(value=self.cfg.get("mic") or "Windows default")
        self.mic_combo = ttk.Combobox(g, textvariable=self.vars["mic"], values=["Windows default"], state="readonly", width=28)
        row(g, 5, "Microphone", self.mic_combo)
        mnames = _WHISPER_NAMES
        self.vars["whisper_model"] = tk.StringVar(value=_LABEL_BY_WHISPER.get(self.cfg.get("whisper_model"), mnames[1]))
        row(g, 6, "Speech recognition", ttk.Combobox(g, textvariable=self.vars["whisper_model"], values=mnames,
                                                     state="readonly", width=28))
        b = ttk.Frame(a, style="Card.TFrame")
        b.pack(fill="x", pady=(8, 0))
        ttk.Button(b, text="Test voice & tones", command=self.test_voice).pack(side="left")
        ttk.Button(b, text="Refresh devices", command=self.refresh_devices).pack(side="left", padx=8)

        cv = self._card(left, fill="x")
        ttk.Label(cv, text="Conversation (AI)", style="Sec.TLabel").pack(anchor="w", pady=(0, 6))
        cg_ai = grid_rows(cv)
        self.vars["ai_provider"] = tk.StringVar(value=AI_PROVIDERS[ai_provider(self.cfg)]["label"])
        prov_combo = ttk.Combobox(cg_ai, textvariable=self.vars["ai_provider"], values=_AI_LABELS, state="readonly",
                                  width=28)
        row(cg_ai, 0, "AI provider", prov_combo, "answers, banter & setups")
        self.key_entries = {}
        for i, (pid, spec) in enumerate(AI_PROVIDERS.items(), start=1):
            kf = ttk.Frame(cg_ai, style="Card.TFrame")
            self.vars[f"{pid}_api_key"] = tk.StringVar(value=self.cfg.get(f"{pid}_api_key") or "")
            ent = ttk.Entry(kf, textvariable=self.vars[f"{pid}_api_key"], width=24, show="•")
            ent.pack(side="left")
            ttk.Button(kf, text="Show", style="Small.TButton", command=lambda e=ent: e.configure(
                show="" if e.cget("show") else "•")).pack(side="left", padx=6)
            self.key_entries[pid] = ent
            row(cg_ai, i, f"{spec['name']} API key", kf, "also used for online speech" if pid == "openai" else "")
            self.vars[f"{pid}_model"] = tk.StringVar(value=ai_model(self.cfg, pid))
        self.key_entry = self.key_entries["openai"]
        self.model_combo = ttk.Combobox(cg_ai, width=28)
        row(cg_ai, len(AI_PROVIDERS) + 1, "Model", self.model_combo)

        def on_provider(_e=None):
            pid = _AI_BY_LABEL.get(self.vars["ai_provider"].get(), "openai")
            self.model_combo.configure(textvariable=self.vars[f"{pid}_model"], values=AI_PROVIDERS[pid]["models"])
            self.model_combo.set(self.vars[f"{pid}_model"].get())
            if hasattr(self, "key_lbl"):
                self.key_lbl.configure(text="")
        prov_combo.bind("<<ComboboxSelected>>", on_provider)
        self.vars["ai_fallback"] = tk.BooleanVar(value=bool(self.cfg.get("ai_fallback", True)))
        ttk.Checkbutton(cv, text="If the provider is down or busy, try my other keys", variable=self.vars["ai_fallback"]
                        ).pack(anchor="w", pady=(6, 0))
        kb = ttk.Frame(cv, style="Card.TFrame")
        kb.pack(fill="x", pady=(8, 0))
        ttk.Button(kb, text="Get an API key", command=lambda: self._open(
            AI_PROVIDERS[_AI_BY_LABEL.get(self.vars["ai_provider"].get(), "openai")]["key_url"])).pack(side="left")
        ttk.Button(kb, text="Test key", command=self.test_key).pack(side="left", padx=8)
        self.key_lbl = ttk.Label(kb, text="", style="Mut.TLabel", wraplength=300)
        self.key_lbl.pack(side="left")
        on_provider()

        w = self._card(right, fill="x", pady=(0, 8))
        ttk.Label(w, text="Wheel buttons", style="Sec.TLabel").pack(anchor="w", pady=(0, 6))
        wg = grid_rows(w)
        self.bind_lbls = {}
        for r_, (action, label) in enumerate(BUTTON_ACTIONS):
            ttk.Label(wg, text=label, style="Card.TLabel", width=21).grid(row=r_, column=0, sticky="w", pady=4)
            lbl = ttk.Label(wg, text=self.controls.describe(action), style="Mut.TLabel", width=20)
            lbl.grid(row=r_, column=1, sticky="w")
            self.bind_lbls[action] = lbl
            ttk.Button(wg, text="Set", style="Small.TButton",
                       command=lambda a=action: self.bind_action(a)).grid(row=r_, column=2, padx=4)
            ttk.Button(wg, text="Clear", style="Small.TButton",
                       command=lambda a=action: self.clear_action(a)).grid(row=r_, column=3)
        ttk.Label(w, text="Click Set, then press the button on your wheel. Works while the game is focused.",
                  style="Mut.TLabel", wraplength=420, justify="left").pack(anchor="w", pady=(6, 0))

        c = self._card(right, fill="x")
        ttk.Label(c, text="Coaching", style="Sec.TLabel").pack(anchor="w", pady=(0, 6))
        cg = grid_rows(c)
        lv = ttk.Frame(cg, style="Card.TFrame")
        self.vars["talk_level"] = tk.IntVar(value=self.cfg.get("talk_level", 1))
        for val, txt in ((0, "Quiet"), (1, "Normal"), (2, "Chatty")):
            ttk.Radiobutton(lv, text=txt, value=val, variable=self.vars["talk_level"]).pack(side="left", padx=(0, 10))
        row(cg, 0, "How much it talks", lv)
        pnames = _PERSONALITY_NAMES
        self.vars["coach_personality"] = tk.StringVar(
            value=_LABEL_BY_PERSONALITY.get(self.cfg.get("coach_personality", DEFAULT_CONFIG["coach_personality"]), pnames[0])
        )
        row(cg, 1, "Coach personality",
            ttk.Combobox(cg, textvariable=self.vars["coach_personality"], values=pnames, state="readonly", width=38))
        bc = ttk.Frame(cg, style="Card.TFrame")
        self.vars["brake_callouts"] = tk.StringVar(value=self.cfg.get("brake_callouts", "focus"))
        for val, txt in (("focus", "Focus corners"), ("all", "Every corner"), ("off", "Off")):
            ttk.Radiobutton(bc, text=txt, value=val, variable=self.vars["brake_callouts"]).pack(side="left", padx=(0, 10))
        row(cg, 2, "Braking tones", bc)
        self.vars["split_callouts"] = tk.BooleanVar(value=bool(self.cfg.get("split_callouts")))
        ttk.Checkbutton(c, text="Split deltas: say the gap to your best at 1/3 and 2/3 of the lap",
                        variable=self.vars["split_callouts"]).pack(anchor="w", pady=2)
        self.vars["auto_start"] = tk.BooleanVar(value=bool(self.cfg.get("auto_start")))
        ttk.Checkbutton(c, text="Start coaching automatically when SimCoach opens",
                        variable=self.vars["auto_start"]).pack(anchor="w", pady=2)
        self.vars["starter_laps"] = tk.BooleanVar(value=bool(self.cfg.get("starter_laps", True)))
        ttk.Checkbutton(c, text="Starter laps: coach from lap one at known tracks",
                        variable=self.vars["starter_laps"]).pack(anchor="w", pady=2)
        self.vars["shared_refs"] = tk.BooleanVar(value=bool(self.cfg.get("shared_refs", True)))
        ttk.Checkbutton(c, text="Use and auto-import reference laps from the SimCoach library",
                        variable=self.vars["shared_refs"]).pack(anchor="w", pady=2)
        pf = ttk.Frame(c, style="Card.TFrame")
        pf.pack(anchor="w", pady=(6, 0))
        ttk.Label(pf, text="F1 25 UDP port", style="Card.TLabel").pack(side="left")
        self.vars["f1_port"] = tk.StringVar(value=str(self.cfg.get("f1_port", 20777)))
        ttk.Entry(pf, textvariable=self.vars["f1_port"], width=8).pack(side="left", padx=8)
        ttk.Label(pf, text="also listens on 20778 (SimHub)", style="Mut.TLabel").pack(side="left")
        self.vars["udp_share_simhub"] = tk.BooleanVar(value=bool(self.cfg.get("udp_share_simhub", True)))
        ttk.Checkbutton(c, text="Share F1 25 / DiRT Rally 2.0 telemetry with SimHub",
                        variable=self.vars["udp_share_simhub"]).pack(anchor="w", pady=(4, 0))
        self.vars["second_screen"] = tk.BooleanVar(value=bool(self.cfg.get("second_screen")))
        ttk.Checkbutton(c, text="Phone / tablet live screen (see the Phone screen button up top)",
                        variable=self.vars["second_screen"]).pack(anchor="w", pady=(4, 0))
        self.screen_lbl = ttk.Label(c, text="", style="Mut.TLabel")
        self.screen_lbl.pack(anchor="w")
        uf = ttk.Frame(c, style="Card.TFrame")
        uf.pack(anchor="w", pady=(4, 0), fill="x")
        self.vars["check_updates"] = tk.BooleanVar(value=bool(self.cfg.get("check_updates", True)))
        ttk.Checkbutton(uf, text="Tell me when an update is out", variable=self.vars["check_updates"]).pack(side="left")
        ttk.Button(uf, text="Check now", style="Small.TButton",
                   command=lambda: (self.upd_lbl.configure(text="Checking…"), self.check_for_updates(manual=True))
                   ).pack(side="left", padx=8)
        self.upd_lbl = ttk.Label(c, text=f"You have SimCoach {APP_VERSION}.", style="Mut.TLabel")
        self.upd_lbl.pack(anchor="w")

        rc = self._card(right, fill="x", pady=(8, 0))
        ttk.Label(rc, text="Race engineer, strategist & spotter", style="Sec.TLabel").pack(anchor="w", pady=(0, 2))
        ttk.Label(rc, text="They introduce themselves, report after every lap, react and chat, each in their own voice.",
                  style="Mut.TLabel", wraplength=560, justify="left").pack(anchor="w", pady=(0, 6))
        crg = grid_rows(rc)
        vnames = _VOICE_NAMES
        for r_, (role, label, default_voice) in enumerate(CREW_ROLES):
            self.vars[f"{role}_on"] = tk.BooleanVar(value=bool(self.cfg.get(f"{role}_on", True)))
            ttk.Checkbutton(crg, text=label, variable=self.vars[f"{role}_on"]).grid(row=r_, column=0, sticky="w", pady=3)
            cur = self.cfg.get(f"{role}_voice") or default_voice
            self.vars[f"{role}_voice"] = tk.StringVar(value=_LABEL_BY_VOICE.get(cur, vnames[0]))
            ttk.Combobox(crg, textvariable=self.vars[f"{role}_voice"], values=vnames, state="readonly",
                         width=19).grid(row=r_, column=1, sticky="w", padx=8, pady=3)
        for r_, (label, key, opts, default) in enumerate((("Lap reports", "crew_updates", CREW_UPDATES, DEFAULT_CONFIG["crew_updates"]),
                                                          ("Chatter", "crew_chatter", CREW_CHATTER, "normal"),
                                                          ("Language", "crew_language", CREW_LANGUAGE, "clean"),
                                                          ("Setup briefing", "briefing_mode", BRIEFING_MODES, "daily"))):
            ttk.Label(crg, text=label, style="Card.TLabel").grid(row=r_, column=2, sticky="w", padx=(14, 6), pady=3)
            self.vars[key] = tk.StringVar(value=dict((v, k) for k, v in opts).get(self.cfg.get(key, default),
                                                                                    dict((v, k) for k, v in opts)[default]))
            ttk.Combobox(crg, textvariable=self.vars[key], values=[k for k, _ in opts], state="readonly",
                         width=18).grid(row=r_, column=3, sticky="w", pady=3)
        self.vars["sheet_autopop"] = tk.BooleanVar(value=bool(self.cfg.get("sheet_autopop", True)))
        ttk.Checkbutton(rc, text="Open the setup sheet at the start of each session",
                        variable=self.vars["sheet_autopop"]).pack(anchor="w", pady=(6, 0))
        ttk.Label(rc, text="Spotter calls the wrong side? Swap left/right in:", style="Card.TLabel").pack(anchor="w", pady=(8, 0))
        sw = ttk.Frame(rc, style="Card.TFrame")
        sw.pack(anchor="w", pady=(2, 0))
        swapped = self.cfg.get("spotter_swap") or []
        for game in SPOTTER_GAMES:
            self.vars[f"swap_{game}"] = tk.BooleanVar(value=swapped is True or game in swapped)
            ttk.Checkbutton(sw, text=game, variable=self.vars[f"swap_{game}"]).pack(side="left", padx=(6, 0))
        tb = ttk.Frame(rc, style="Card.TFrame")
        tb.pack(anchor="w", pady=(8, 0))
        ttk.Button(tb, text="Hear the crew", command=self.test_crew).pack(side="left")
        ttk.Label(rc, text="Spotter works in AC (with the CrewChiefEx app on), ACC, LMU, rFactor 2, AMS2, RaceRoom "
                           "and F1 25.",
                  style="Mut.TLabel", wraplength=480, justify="left").pack(anchor="w", pady=(4, 0))

        ttk.Button(foot, text="Save settings", style="Accent.TButton", command=self.save_settings).pack(side="left")
        self.saved_lbl = ttk.Label(foot, text="")
        self.saved_lbl.pack(side="left", padx=12)
        ttk.Button(foot, text="Open log file", command=lambda: self._open(LOG_PATH)).pack(side="right")
        ttk.Button(foot, text="Create desktop shortcut", command=self.make_shortcut).pack(side="right", padx=8)
        ttk.Button(foot, text="Quick setup", command=self._ask_name).pack(side="right")
        self.root.after(300, self.refresh_devices)

    def _references(self):
        ttk = self.ttk
        t = self.tab_ref
        bar = ttk.Frame(t)
        bar.pack(fill="x", pady=(10, 4))
        ttk.Button(bar, text="Delete selected", command=self.delete_ref).pack(side="left")
        ttk.Button(bar, text="Export…", command=self.export_ref).pack(side="left", padx=8)
        ttk.Button(bar, text="Import…", command=self.import_ref).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self.load_refs).pack(side="left", padx=8)
        ttk.Button(bar, text="Share to library…", command=self.share_ref).pack(side="left")
        ttk.Button(bar, text="Update from library", command=lambda: (
            self.share_lbl.configure(text="Checking the library…"), self.sync_library(manual=True))).pack(side="left", padx=8)
        self.share_lbl = ttk.Label(bar, text="", style="Mut.TLabel", wraplength=520)
        self.share_lbl.pack(side="left", padx=10)
        ttk.Label(t, text="Your reference laps (one per sim, track and car). Import a friend's or a quicker "
                          "driver's export to be coached against their lap. New laps shared to the SimCoach library "
                          "are added automatically (your own laps are never replaced).",
                  wraplength=1150, justify="left").pack(anchor="w", pady=(4, 0))
        self.ref_tv = self._tree(t, [("sim", "Sim"), ("track", "Track"), ("car", "Car"), ("best", "Best lap"),
                                     ("corners", "Corners"), ("source", "Source"), ("saved", "Updated")],
                                 (110, 260, 240, 90, 70, 80, 140), 6)
        self.ref_tv.master.pack_configure(expand=False)      # the starter-lap table below takes the spare room
        self.starter_lbl = ttk.Label(t, text="Starter laps", wraplength=1150, justify="left")
        self.starter_lbl.pack(anchor="w", pady=(2, 0))
        self.starter_tv = self._tree(t, [("track", "Circuit"), ("len", "Length"), ("kind", "Starter lap"),
                                         ("gt3", "GT3"), ("gt4", "GT4"), ("proto", "Prototype"), ("f1", "F1"),
                                         ("targets", "Real target times (sim, class or car, lap)")],
                                     (170, 70, 120, 70, 70, 80, 70, 520), 8)
        self._starter_sig = None
        self.load_refs()

    def load_starters(self):
        """Fill the Starter laps table (worked out in the background; redone when tracks or benchmarks change)."""
        sig = (tuple(sorted(starter_tracks())), id(benchmarks()))
        if sig == self._starter_sig:
            return
        self._starter_sig = sig

        def work():
            try:
                self.post(starter_rows=starter_table())
            except Exception as e:
                file_log(f"Starter laps table: {type(e).__name__}: {e}")
        threading.Thread(target=work, daemon=True, name="starter-table").start()

    def _show_starters(self, rows):
        def clock(x):
            return fmt_time(x).replace(" ", ":") if x else "—"
        tv = self.starter_tv
        tv.delete(*tv.get_children())
        for name, length, kind, times, targets in rows:
            tv.insert("", "end", values=(name, f"{length / 1000:.3f} km", kind, clock(times.get("gt3")),
                                         clock(times.get("gt4")), clock(times.get("proto")), clock(times.get("f1")),
                                         targets or "—"))
        n = sum(1 for r in rows if r[2] != "Target times only")
        self.starter_lbl.configure(
            text=f"Starter laps: {n} circuits where coaching starts on lap one, in every supported sim, when you "
                 f"have no lap of your own. The lap is calculated for your car's class (estimated times shown), "
                 f"tuned to the real target time for your sim where there is one, and replaced by your first clean "
                 f"lap. {len(rows) - n} more tracks have target times only.")

    def _ref_files(self):
        try:
            return sorted(f for f in os.listdir(REF_DIR) if f.endswith(".json") and not f.endswith(".sessions.json"))
        except Exception:
            return []

    def load_refs(self):
        """Reference list. Rows are cached by file size + mtime: only new or changed files are parsed
        (each is ~100 KB of JSON; re-reading them all on every report blocked the window)."""
        tv = self.ref_tv
        tv.delete(*tv.get_children())
        self.load_starters()
        cache = self.__dict__.setdefault("_ref_rows", {})
        seen = set()
        for f in self._ref_files():
            path = os.path.join(REF_DIR, f)
            try:
                st = os.stat(path)
                sig = (st.st_size, st.st_mtime_ns)
                hit = cache.get(f)
                if hit is None or hit[0] != sig:
                    with open(path, encoding="utf-8") as fh:
                        d = json.load(fh)
                    key = d.get("key") or f[:-5].split("__") + ["", "", ""]
                    hit = cache[f] = (sig, (key[0], key[1].replace("_", " "), key[2].replace("_", " "),
                                            fmt_time(d.get("best_time") or 0).replace(" ", ":"),
                                            len(d.get("corners", [])),
                                            "Library" if d.get("source") == "library" else "Yours",
                                            d.get("saved", "")))
                seen.add(f)
                tv.insert("", "end", iid=f, values=hit[1])
            except Exception:
                continue
        for f in list(cache):
            if f not in seen:
                del cache[f]

    def share_ref(self):
        """References tab: share the selected lap (the Best laps tab does the work)."""
        sel = self.ref_tv.selection()
        if not sel:
            self.share_lbl.configure(text="Select one of your laps first.")
            return
        if shareable_lap(os.path.join(REF_DIR, sel[0])) is None:
            self.share_lbl.configure(text="Only your own clean laps can be shared (not library laps or laps "
                                          "with an off-track moment).")
            return
        self.nb.select(self.tab_best)
        self.load_best()
        if self.best_tv.exists(sel[0]):
            self.best_tv.selection_set(sel[0])
        self.share_best([sel[0]])

    # ---- Best laps tab: the driver's own best laps, kept ready to share, and sharing them to the library ----
    def _best_laps(self):
        ttk = self.ttk
        t = self.tab_best
        bar = ttk.Frame(t)
        bar.pack(fill="x", pady=(10, 4))
        ttk.Button(bar, text="Share selected", style="Accent.TButton",
                   command=lambda: self.share_best(list(self.best_tv.selection()))).pack(side="left")
        ttk.Button(bar, text="Share all new", command=self.share_all_best).pack(side="left", padx=8)
        ttk.Button(bar, text="Open folder", command=self.open_best_folder).pack(side="left")
        ttk.Button(bar, text="View on GitHub", command=self.view_best).pack(side="left", padx=8)
        self.gh_btn = ttk.Button(bar, text="", command=self.github_account)
        self.gh_btn.pack(side="right")
        self.auto_share_var = self.tk.BooleanVar(value=bool(self.cfg.get("auto_share")))
        ttk.Checkbutton(bar, text="Share new best laps automatically", variable=self.auto_share_var,
                        command=self.toggle_auto_share).pack(side="left", padx=(8, 0))
        self.best_lbl = ttk.Label(t, text="", style="BgMut.TLabel", wraplength=1150, justify="left")
        self.best_lbl.pack(anchor="w", pady=(2, 0))
        ttk.Label(t, text=f"Your best lap for every sim, track and car, saved ready to share in {BEST_DIR}. "
                          "Share one to the SimCoach library and every SimCoach driver gets it automatically. "
                          "Shared: sim, track, car and the lap trace (speed, pedals, steering); never your "
                          "name, settings or keys. Your GitHub username shows on the submission.",
                  wraplength=1150, justify="left").pack(anchor="w", pady=(4, 0))
        self.best_tv = self._tree(t, [("sim", "Sim"), ("track", "Track"), ("car", "Car"), ("best", "Best lap"),
                                      ("saved", "Set"), ("status", "Library")],
                                  (110, 250, 230, 90, 140, 230), 14)
        self.best_tv.bind("<Double-1>", lambda _e: self.view_best())
        self._lib_index = None            # {file name: sha} from the library, refreshed every 10 minutes
        self._lib_index_t = 0.0
        self._gh_label()
        self.root.after(20000, self._best_tick)

    def _best_tick(self):
        def work():
            save_best_laps(REF_DIR, BEST_DIR)
            self.auto_share_best(in_thread=True)
        threading.Thread(target=work, daemon=True, name="best-laps").start()
        self.root.after(10 * 60 * 1000, self._best_tick)

    def auto_share_best(self, in_thread=False):
        """Settings > 'Share new best laps automatically': send new and improved best laps to the library without
        asking each time. Only when signed in to GitHub; the same checks as sharing by hand."""
        if not (self.cfg.get("auto_share") and self.cfg.get("github_token") and self._gh_client_id()) \
                or getattr(self, "_sharing", False):
            return
        token = self.cfg["github_token"]

        def work():
            names = laps_to_auto_share(BEST_DIR, REF_DIR, self.cfg.get("shared_laps") or {})
            if not names:
                return
            self._sharing = True
            self.log(f"Sharing {len(names)} new best lap{'s' if len(names) != 1 else ''} to the library automatically.")
            results, errors = share_laps(BEST_DIR, names, token, log=self.log)
            # a lap that failed for a reason other than sign-in isn't retried every ten minutes
            for name, msg, st in errors:
                if st != 401 and name not in results:
                    try:
                        with open(os.path.join(BEST_DIR, name), "rb") as fh:
                            results[name] = {"sha": git_blob_sha(fh.read()), "status": "refused", "url": msg,
                                             "when": time.strftime("%Y-%m-%d %H:%M")}
                    except OSError:
                        pass
            self.post(best_shared=(results, errors))
        if in_thread:
            work()
        else:
            threading.Thread(target=work, daemon=True, name="auto-share").start()

    def toggle_auto_share(self):
        from tkinter import messagebox
        on = bool(self.auto_share_var.get())
        if on and not self._gh_client_id():
            self.auto_share_var.set(False)
            self.best_lbl.configure(text="Automatic sharing needs in-app GitHub sign-in, which this copy doesn't have.")
            return
        if on and not messagebox.askyesno(
                "SimCoach", "Share every new best lap to the public SimCoach library automatically?\n\n"
                            "Shared: sim, track, car and the lap trace. Your GitHub username shows on each submission. "
                            "You can switch this off here at any time."):
            self.auto_share_var.set(False)
            return
        self.cfg["auto_share"] = on
        save_config(self.cfg)
        if on and not self.cfg.get("github_token"):
            self.github_sign_in(then=self.auto_share_best)
        elif on:
            self.auto_share_best()

    def _gh_client_id(self):
        return (self.cfg.get("github_client_id") or GITHUB_CLIENT_ID or "").strip()

    def _gh_label(self):
        who = self.cfg.get("github_login")
        self.gh_btn.configure(text=f"GitHub: {who} · Sign out" if self.cfg.get("github_token") and who
                              else "Sign in to GitHub")

    def github_account(self):
        from tkinter import messagebox
        if self.cfg.get("github_token"):
            if messagebox.askyesno("SimCoach", "Sign out of GitHub on this PC?"):
                self.cfg["github_token"] = ""
                self.cfg["github_login"] = ""
                save_config(self.cfg)
                self._gh_label()
            return
        self.github_sign_in()

    def github_sign_in(self, then=None):
        """GitHub's sign-in for apps: SimCoach shows a short code, the driver enters it on github.com (no password
        goes through SimCoach). The token only allows working with public repositories."""
        cid = self._gh_client_id()
        if not cid:
            self.best_lbl.configure(text="In-app sharing isn't set up in this copy; use Share selected to share "
                                         "through the GitHub web page instead.")
            return
        if getattr(self, "_gh_dialog", None) is not None:
            return
        tk, ttk = self.tk, self.ttk
        dlg = self._gh_dialog = tk.Toplevel(self.root)
        dlg.title("Sign in to GitHub")
        dlg.configure(bg=C["bg"])
        dlg.transient(self.root)
        box = ttk.Frame(dlg, padding=20)
        box.pack(fill="both", expand=True)
        msg = ttk.Label(box, text="Getting a sign-in code…", wraplength=380)
        msg.pack(anchor="w")
        code = ttk.Label(box, text="", style="H.TLabel")
        code.pack(pady=12)
        btns = ttk.Frame(box)
        btns.pack(fill="x")
        go = ttk.Button(btns, text="Copy code and open GitHub", style="Accent.TButton", state="disabled")
        go.pack(side="left")
        state = {"cancel": False}

        def close():
            state["cancel"] = True
            self._gh_dialog = None
            try:
                dlg.destroy()
            except Exception:
                pass
        ttk.Button(btns, text="Cancel", command=close).pack(side="right")
        dlg.protocol("WM_DELETE_WINDOW", close)

        def shown(start):
            if state["cancel"]:
                return
            msg.configure(text="Enter this code on the GitHub page, then allow SimCoach. This window closes by "
                               "itself when you're done.")
            code.configure(text=start["user_code"])

            def copy_open():
                self.root.clipboard_clear()
                self.root.clipboard_append(start["user_code"])
                self._open(start.get("verification_uri") or f"{GITHUB_WEB}/login/device")
            go.configure(state="normal", command=copy_open)
            copy_open()

        def work():
            try:
                start = github_device_start(cid)
                self.root.after(0, lambda: shown(start))
                token = github_device_poll(cid, start, cancelled=lambda: state["cancel"])
                login = _gh_call("GET", f"{GITHUB_API}/user", token).get("login", "")
                self.post(gh_signed_in=(token, login, then))
            except Exception as e:
                if not state["cancel"]:
                    self.post(gh_error=f"GitHub sign-in didn't finish: {e}")
            finally:
                self.root.after(0, close)
        threading.Thread(target=work, daemon=True, name="github-sign-in").start()

    def _gh_signed_in(self, ev):
        token, login, then = ev
        self.cfg["github_token"] = token
        self.cfg["github_login"] = login
        save_config(self.cfg)
        self._gh_label()
        self.best_lbl.configure(text=f"Signed in to GitHub as {login}.")
        if then:
            then()

    def load_best(self):
        """Your own clean best laps with their library status (refreshes the Best laps folder first)."""
        save_best_laps(REF_DIR, BEST_DIR)
        tv = self.best_tv
        keep = set(tv.selection())
        tv.delete(*tv.get_children())
        idx = self._lib_index
        shared = self.cfg.get("shared_laps") or {}
        try:
            names = sorted(f for f in os.listdir(BEST_DIR) if f.endswith(".json"))
        except OSError:
            names = []
        for name in names:
            if not os.path.exists(os.path.join(REF_DIR, name)):
                continue                  # the reference was deleted (or replaced by a library lap)
            try:
                with open(os.path.join(BEST_DIR, name), "rb") as fh:
                    data = fh.read()
                d = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            sha = git_blob_sha(data)
            rec = shared.get(name) or {}
            if idx is not None and idx.get(name) == sha:
                status = "In the library ✓"
            elif rec.get("sha") == sha and rec.get("status") == "proposed":
                status = rec.get("verdict") or "Sent · being checked"
            elif rec.get("sha") == sha and rec.get("status") == "refused":
                status = "Not added: " + str(rec.get("url"))
            elif rec.get("sha") == sha:
                status = "In the library ✓"
            elif idx is not None and name in idx:
                status = "Library has a different lap"
            elif rec:
                status = "Faster than the lap you shared"
            else:
                status = "Not shared"
            k = d.get("key") or ["", "", ""]
            tv.insert("", "end", iid=name, values=(k[0], k[1].replace("_", " "), k[2].replace("_", " "),
                                                   fmt_time(d.get("best_time") or 0).replace(" ", ":"),
                                                   d.get("saved", ""), status))
        for n in keep:
            if tv.exists(n):
                tv.selection_add(n)
        if not names:
            self.best_lbl.configure(text="No best laps yet: drive a clean lap and it's saved here.")
        if self.cfg.get("shared_refs", True) and time.monotonic() - self._lib_index_t > 600:
            self._lib_index_t = time.monotonic()

            pending = {n: r for n, r in shared.items() if r.get("status") == "proposed" and not r.get("verdict")}

            def fetch():
                try:
                    idx = {it["name"]: it["sha"] for it in list_library()}
                except Exception as e:
                    file_log(f"Library list failed: {e}")
                    return
                verdicts = {}
                for n, r in pending.items():         # sent laps the library doesn't have: did the check refuse them?
                    m = re.search(r"/pull/(\d+)", str(r.get("url")))
                    if not m or idx.get(n) == r.get("sha"):
                        continue
                    try:
                        pr = _gh_call("GET", f"{GITHUB_API}/repos/{UPDATE_REPO}/pulls/{m.group(1)}",
                                      self.cfg.get("github_token") or None, timeout=8.0)
                        if pr.get("state") == "closed":
                            verdicts[n] = "Not added (View on GitHub says why)"
                    except Exception:
                        pass
                self.post(lib_index=(idx, verdicts))
            threading.Thread(target=fetch, daemon=True, name="library-list").start()

    def open_best_folder(self):
        save_best_laps(REF_DIR, BEST_DIR)
        os.makedirs(BEST_DIR, exist_ok=True)
        self._open(BEST_DIR)

    def view_best(self):
        sel = self.best_tv.selection()
        rec = (self.cfg.get("shared_laps") or {}).get(sel[0]) if sel else None
        if rec and str(rec.get("url", "")).startswith("http"):
            self._open(rec["url"])
        else:
            self._open(f"{GITHUB_WEB}/{UPDATE_REPO}/tree/main/references")

    def share_all_best(self):
        self.load_best()
        names = [n for n in self.best_tv.get_children()
                 if not str(self.best_tv.set(n, "status")).startswith(("In the library", "Sent", "Not added"))]
        if not names:
            self.best_lbl.configure(text="Nothing new to share: every best lap is in the library, on its way, or "
                                         "slower than the library's.")
            return
        self.share_best(names)

    def share_best(self, names):
        from tkinter import messagebox
        names = [n for n in names if os.path.exists(os.path.join(BEST_DIR, n))]
        if not names:
            self.best_lbl.configure(text="Select one of your best laps first.")
            return
        if not self._gh_client_id():                 # not set up for in-app sharing: the GitHub upload page
            os.makedirs(BEST_DIR, exist_ok=True)
            self._open(BEST_DIR)
            self._open(f"{GITHUB_WEB}/{UPDATE_REPO}/upload/main/references")
            self.best_lbl.configure(text=f"Drag {', '.join(names)} from the folder that opened onto the GitHub "
                                         f"page, then Commit (others propose it and the owner approves).")
            return
        if not self.cfg.get("github_token"):
            self.github_sign_in(then=lambda: self.share_best(names))
            return
        if getattr(self, "_sharing", False):
            return
        n = len(names)
        if not messagebox.askyesno("SimCoach", f"Share {n} best lap{'s' if n != 1 else ''} to the public SimCoach "
                                               "library?\n\nShared: sim, track, car and the lap trace. Your GitHub "
                                               "username shows on the submission."):
            return
        self._sharing = True
        self.best_lbl.configure(text=f"Sharing {n} lap{'s' if n != 1 else ''}…")
        token = self.cfg["github_token"]

        def work():
            self.post(best_shared=share_laps(BEST_DIR, names, token, log=self.log))
        threading.Thread(target=work, daemon=True, name="share-laps").start()

    def _best_shared(self, ev):
        results, errors = ev
        self._sharing = False
        shared = dict(self.cfg.get("shared_laps") or {})
        shared.update(results)
        self.cfg["shared_laps"] = shared
        if any(st == 401 for _n, _m, st in errors):
            self.cfg["github_token"] = ""
            self.cfg["github_login"] = ""
            self._gh_label()
        save_config(self.cfg)
        refused = {n: r for n, r in results.items() if r["status"] == "refused"}
        added = sum(1 for r in results.values() if r["status"] == "added")
        sent = sum(1 for r in results.values() if r["status"] == "proposed")
        parts = []
        if added:
            parts.append(f"{added} added to the library (everyone gets {'them' if added > 1 else 'it'} at their "
                         f"next library check)")
        if sent:
            parts.append(f"{sent} sent: checked and added to the library automatically in a minute or two")
        for n, r in refused.items():
            parts.append(f"{n[:-5].replace('__', ' · ')} not added: {r['url']}")
        for name, msg, st in errors:
            self.log(f"Couldn't share {name}: {msg}")
        if errors:
            parts.append(f"{len(errors)} not shared: {errors[0][1]}"
                         + (" (sign in again)" if any(st == 401 for _n, _m, st in errors) else ""))
        self.best_lbl.configure(text=("; ".join(parts) + ".") if parts else "")
        if added:
            self._lib_index_t = 0.0      # re-read the library's list
        self.load_best()

    def delete_ref(self):
        from tkinter import messagebox
        sel = self.ref_tv.selection()
        if not sel or not messagebox.askyesno("SimCoach", "Delete the selected reference lap(s)? "
                                                          "The next clean lap there becomes the new reference."):
            return
        for f in sel:
            path = os.path.join(REF_DIR, f)
            try:
                with open(path, encoding="utf-8") as fh:
                    key = json.load(fh).get("key")
            except Exception:
                key = None
            self.coach.delete_saved_reference(key, (path, path.replace(".json", ".sessions.json")))
        self.load_refs()

    def export_ref(self):
        from tkinter import filedialog
        import shutil
        sel = self.ref_tv.selection()
        if not sel:
            return
        dest = filedialog.asksaveasfilename(defaultextension=".json", initialfile=f"SimCoach_{sel[0]}",
                                            filetypes=[("SimCoach reference", "*.json")])
        if dest:
            shutil.copyfile(os.path.join(REF_DIR, sel[0]), dest)
            self.log(f"Exported reference to {dest}")

    def import_ref(self):
        from tkinter import filedialog, messagebox
        src = filedialog.askopenfilename(filetypes=[("SimCoach reference", "*.json")])
        if not src:
            return
        try:
            with open(src, encoding="utf-8") as fh:
                d = json.load(fh)
            prob = ref_problem(d)
        except Exception as e:
            prob = f"unreadable ({e})"
        if prob:
            messagebox.showerror("SimCoach", f"That file isn't a usable SimCoach reference export: {prob}.")
            return
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", "__".join(d["key"])) + ".json"
        dest = os.path.join(REF_DIR, name)
        if os.path.exists(dest) and not messagebox.askyesno("SimCoach", "Replace your existing reference for this "
                                                                        "sim, track and car?"):
            return
        try:
            self.coach.import_reference(d, dest)
        except OSError as e:
            messagebox.showerror("SimCoach", f"Couldn't save the imported reference:\n{e}")
            return
        self.log(f"Imported reference: {' / '.join(d['key'])}")
        self.load_refs()

    def _reports(self):
        ttk = self.ttk
        t = self.tab_rep
        bar = ttk.Frame(t)
        bar.pack(fill="x", pady=(10, 4))
        ttk.Button(bar, text="Open selected", style="Accent.TButton", command=self.open_report).pack(side="left")
        ttk.Button(bar, text="Open folder", command=lambda: self._open(ensure_report_dir())).pack(side="left", padx=8)
        ttk.Button(bar, text="Write report now", command=self.write_report_now).pack(side="left")
        ttk.Button(bar, text="Delete selected", command=self.delete_report).pack(side="left", padx=8)
        ttk.Button(bar, text="Refresh", command=self.load_reports).pack(side="left")
        self.rep_status = ttk.Label(bar, text="", foreground=C["mut"])
        self.rep_status.pack(side="left", padx=12)
        self.rep_tv = self._tree(t, [("date", "Date"), ("name", "Session")], (160, 820), 16)
        self.rep_tv.bind("<Double-1>", lambda e: self.open_report())
        self.rep_tv.bind("<Delete>", lambda e: self.delete_report())
        self.load_reports()

    def _log(self):
        tk, ttk = self.tk, self.ttk
        bar = ttk.Frame(self.tab_log)
        bar.pack(fill="x", pady=(10, 0))
        self.cap_btn = ttk.Button(bar, text=f"Capture {CAPTURE_DEFAULT_S} s of game data", command=self._capture_click)
        self.cap_btn.pack(side="left")
        ttk.Button(bar, text="Open captures folder", command=self._open_captures).pack(side="left", padx=8)
        self.cap_lbl = ttk.Label(bar, text="", style="Mut.TLabel")
        self.cap_lbl.pack(side="left", padx=8)
        self._cap_shown = None
        self.root.after(500, self._cap_refresh)
        f = self._card(self.tab_log, fill="both", expand=True, pady=10)
        self.log_txt = tk.Text(f, bg=C["panel"], fg=C["fg"], insertbackground=C["fg"], relief="flat", bd=0, highlightthickness=0,
                               padx=8, pady=6, selectbackground=C["acc"],
                               font=self._font(10, mono=True), wrap="word", height=20)
        self.log_txt.pack(fill="both", expand=True)
        self.log_txt.tag_configure("coach", foreground=C["tip"])
        self.log_txt.tag_configure("driver", foreground=C["violet"])

    def _capture_click(self):
        self.log(self.coach.capture.toggle())
        self._cap_refresh(again=False)

    def _open_captures(self):
        try:
            os.makedirs(capture_dir(), exist_ok=True)
        except Exception:
            pass
        self._open(capture_dir())

    def _cap_refresh(self, again=True):
        """Keep the Log tab's capture button and status line in step with the capture (twice a second)."""
        cap = self.coach.capture
        busy = bool(cap.active or cap.want)
        st = cap.status() or ('Records what the sim sends, so SimCoach can be checked against a real session. '
                              'Say "start capture" while driving, or bind a wheel button to it.')
        if (busy, st) != self._cap_shown:
            self._cap_shown = (busy, st)
            try:
                self.cap_btn.configure(text="Stop capture" if busy else f"Capture {CAPTURE_DEFAULT_S} s of game data")
                self.cap_lbl.configure(text=st)
            except Exception:
                return
        if again:
            self.root.after(500, self._cap_refresh)

    def _open(self, target):
        """Open a file, folder or URL: Windows shell first, then Explorer, then the web browser."""
        is_url = "://" in str(target)
        if not is_url and not os.path.exists(target):
            self.log(f"Couldn't open {target}: it doesn't exist")
            return
        attempts = []
        if sys.platform == "win32":
            attempts.append(lambda: os.startfile(target))
            if not is_url:
                import subprocess
                attempts.append(lambda: subprocess.Popen(["explorer", os.path.normpath(target)]))
        import webbrowser
        from pathlib import Path
        attempts.append(lambda: webbrowser.open(target if is_url else Path(target).resolve().as_uri()))
        for go in attempts:
            try:
                go()
                return
            except Exception as e:
                err = e
        self.log(f"Couldn't open {target}: {err}")

    def log(self, msg):
        self.logq.put(f"{time.strftime('%H:%M:%S')}  {msg}")
        file_log(msg)
        print(msg)

    def post(self, **kw):
        live = self.__dict__.setdefault("_live", {})
        for k in ("delta", "delta_color", "focus", "tip"):
            if k in kw:
                live[k] = kw[k]
        self.inbox.put(kw)

    def _screen_data(self):
        """What the phone page shows (read without the coach lock: display values only)."""
        c, live = self.coach, dict(getattr(self, "_live", {}))
        with c.lock:                     # a consistent copy: the telemetry thread updates these
            f = c.last_frame if c.live() else None
            best_t = c.best_time
            fpl = c.crew.fuel_per_lap() if (f is not None and c.crew) else None

        def text(x):  # spoken spellings back to written ones
            if not x:
                return None
            x = re.sub(r"^Focus\s+·\s+", "", str(x)).replace(" k p h", " km/h")
            return _RE_SPOKEN_TIME.sub(r"\1:\2", x)

        def lap(t):
            return fmt_time(t).replace(" ", ":", 1)
        d = {"version": APP_VERSION, "live": f is not None, "delta": live.get("delta", "--.--"),
             "delta_color": live.get("delta_color"), "focus": text(live.get("focus")), "coach": text(live.get("tip"))}
        if f is None:
            return d
        d.update(sim=f.game, track=nice_name(f.track), car=nice_name(f.car), lap=f.laps_done + 1,
                 last=lap(f.last_time) if f.last_time > 10 else None,
                 best=lap(best_t) if best_t else None, pos=f.position or None, cars=f.cars or None,
                 gap_ahead=f.gap_ahead, gap_behind=f.gap_behind, speed=int(round(f.speed)), gear=f.gear,
                 fuel=(f"{f.fuel:.1f} {'kg' if f.game in KG_FUEL_GAMES else 'L'}" if f.fuel > 0 else None),
                 fuel_laps=(int(f.fuel / fpl) if (fpl and f.fuel > 0) else None))
        return d

    # --- updates -----------------------------------------------------------------------------------------------
    def _update_tick(self):
        """Check now, then every 12 hours while SimCoach is open."""
        if self.cfg.get("check_updates", True):
            self.check_for_updates()
        self.root.after(12 * 3600 * 1000, self._update_tick)

    def check_for_updates(self, manual=False):
        def work():
            try:
                info = check_latest_release()
            except Exception as e:
                file_log(f"Update check failed: {type(e).__name__}: {e}")
                if manual:
                    self.post(update_status="Couldn't reach GitHub to check for updates.")
                return
            if info is None:
                if manual:
                    self.post(update_status=f"You're up to date (SimCoach {APP_VERSION}).")
                return
            if not manual and info["tag"] == self.cfg.get("update_skip"):
                return
            self.post(update=info, update_status=f"SimCoach {info['version']} is available.")
        threading.Thread(target=work, daemon=True, name="update-check").start()

    def _show_update(self, info):
        tk, ttk = self.tk, self.ttk
        self.update_info = info
        bar = getattr(self, "update_bar", None)
        if bar is not None:
            bar.destroy()
        bar = self.update_bar = tk.Frame(self.root, bg="#132640", highlightbackground=C["acc"], highlightthickness=1)
        tk.Label(bar, text=f"SimCoach {info['version']} is available", bg="#132640", fg=C["fg"],
                 font=self._font(10, True)).pack(side="left", padx=(12, 6), pady=8)
        self.update_msg = tk.Label(bar, text=f"You have {APP_VERSION}.", bg="#132640", fg=C["mut"], font=self._font(9))
        self.update_msg.pack(side="left")
        ttk.Button(bar, text="Not now", style="Small.TButton", command=self._skip_update).pack(side="right", padx=(4, 10))
        ttk.Button(bar, text="What's new", style="Small.TButton",
                   command=lambda: self._open(info["url"])).pack(side="right", padx=4)
        can_install = sys.platform == "win32" and installed_copy()
        self.update_btn = ttk.Button(bar, text="Install update" if can_install else "Download",
                                     style="Accent.TButton",
                                     command=self._install_update if can_install else (lambda: self._open(info["url"])))
        self.update_btn.pack(side="right", padx=4)
        bar.pack(fill="x", padx=18, pady=(8, 0), before=self.nb)
        self.log(f"Update available: SimCoach {info['version']} ({info['url']})")

    def _library_tick(self):
        """Keep the reference folder in step with the shared library: now, then every 12 hours."""
        if self.cfg.get("shared_refs", True):
            self.sync_library()
        self.root.after(12 * 3600 * 1000, self._library_tick)

    def sync_library(self, manual=False):
        if getattr(self, "_syncing", False):
            return
        self._syncing = True

        def work():
            try:
                seen = dict(self.cfg.get("library_seen") or {})
                added, updated = sync_library(self.coach, seen, REF_DIR, log=self.log)
                self.cfg["library_seen"] = seen
                tracks = []
                try:
                    tseen = dict(self.cfg.get("library_tracks_seen") or {})
                    tracks = sync_library_tracks(tseen, log=self.log)
                    self.cfg["library_tracks_seen"] = tseen
                    if tracks:
                        self.log(f"Starter laps added for: {', '.join(tracks)}")
                    if sync_library_benchmarks(log=self.log):
                        self.log("Benchmark lap times updated from the library.")
                except Exception as e:
                    file_log(f"Library track sync failed: {type(e).__name__}: {e}")
                save_config(self.cfg)
                parts = []
                if added or updated:
                    parts.append(f"{len(added)} new reference lap{'s' if len(added) != 1 else ''}"
                                 + (f", {len(updated)} updated" if updated else ""))
                if tracks:
                    parts.append(f"starter laps for {len(tracks)} more track{'s' if len(tracks) != 1 else ''}")
                msg = ("Library: " + "; ".join(parts) + "." if parts else
                       "Library: you have everything in it." if manual else "")
                for k in added + updated:
                    self.log(f"Library lap {'updated' if k in updated else 'added'}: {k[0]} · {k[1]} · {k[2]}")
                self.post(library_sync=msg)
            except Exception as e:
                file_log(f"Library sync failed: {type(e).__name__}: {e}")
                self.post(library_sync="Couldn't reach the SimCoach library." if manual else "")
            finally:
                self._syncing = False
        threading.Thread(target=work, daemon=True, name="library-sync").start()

    def _skip_update(self):
        if self.update_info:
            self.cfg["update_skip"] = self.update_info["tag"]
            save_config(self.cfg)
        bar, self.update_bar = getattr(self, "update_bar", None), None
        if bar is not None:
            bar.destroy()

    def _install_update(self):
        info = self.update_info
        if not info or getattr(self, "_updating", False):
            return
        self._updating = True
        self.update_btn.configure(state="disabled")
        dest = os.path.join(tempfile.gettempdir(), f"SimCoach-Setup-{_RE_SAFE_REPORT.sub('_', info['tag'])}.exe")

        def work():
            try:
                download_installer(info["installer_url"], dest,
                                   progress=lambda got, total: self.post(update_progress=(got, total)))
                self.post(update_progress="run")
                import subprocess
                subprocess.Popen([dest], close_fds=True)
            except Exception as e:
                file_log(f"Update download failed: {type(e).__name__}: {e}")
                self.post(update_progress=f"error:{e}")
            finally:
                self._updating = False
        threading.Thread(target=work, daemon=True, name="update-download").start()

    def _update_progress(self, p):
        if not getattr(self, "update_bar", None):
            return
        if p == "run":
            self.update_msg.configure(text="Installer started: it closes SimCoach (your session is saved) and updates it.")
        elif isinstance(p, str) and p.startswith("error:"):
            self.update_msg.configure(text="Download failed. Use What's new to get it from GitHub.", fg=C["bad"])
            self.update_btn.configure(state="normal")
        else:
            got, total = p
            self.update_msg.configure(text=f"Downloading… {got * 100 // total}%" if total else
                                      f"Downloading… {got // 1024} KB")

    def phone_screen_dialog(self):
        """Top bar > Phone screen: switch the live page for a phone or tablet on, and show how to open it
        (address, QR code to scan, copy / test buttons)."""
        if getattr(self, "_phone_dlg", None) is not None:
            try:
                self._phone_dlg.lift()
                return
            except Exception:
                self._phone_dlg = None
        tk, ttk = self.tk, self.ttk
        dlg = self._phone_dlg = tk.Toplevel(self.root)
        dlg.title("Phone / tablet screen")
        dlg.configure(bg=C["bg"])
        dlg.transient(self.root)
        dlg.resizable(False, False)
        box = ttk.Frame(dlg, padding=20)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="Live screen on your phone or tablet", style="H.TLabel").pack(anchor="w")
        ttk.Label(box, wraplength=440, justify="left",
                  text="A big live delta, lap times, position, gaps, fuel and the coach's last call. "
                       "Read-only: nothing on the page can change SimCoach.").pack(anchor="w", pady=(4, 10))
        steps = ttk.Label(box, wraplength=440, justify="left", text="")
        steps.pack(anchor="w")
        qr = tk.Canvas(box, width=10, height=10, bg="white", highlightthickness=0)
        addr = tk.Entry(box, font=("Segoe UI", 13, "bold"), width=36, relief="flat", readonlybackground=C["panel2"],
                        fg=C["fg"], justify="center")
        note = ttk.Label(box, wraplength=440, justify="left", style="BgMut.TLabel", text="")
        btns = ttk.Frame(box)
        onoff = ttk.Button(btns, text="")
        copy_b = ttk.Button(btns, text="Copy address")
        test_b = ttk.Button(btns, text="Test on this PC")

        def close():
            self._phone_dlg = None
            dlg.destroy()

        def set_on(on):
            self.cfg["second_screen"] = bool(on)
            if "second_screen" in self.vars:
                self.vars["second_screen"].set(bool(on))
            save_config(self.cfg)
            self._apply_second_screen()
            show()

        def show():
            url = self.screen.url() if self.screen.running() else ""
            for w in (qr, addr, note):
                w.pack_forget()
            offline = url.startswith("http://127.")
            if offline:
                steps.configure(text="This PC isn't connected to a network, so a phone can't reach it. Connect the PC "
                                     "to your Wi-Fi or router, then close and reopen this window.")
                note.configure(text="")
                onoff.configure(text="Turn off", command=lambda: set_on(False))
                copy_b.configure(state="disabled")
                test_b.configure(state="normal", command=lambda: self._open(
                    f"http://127.0.0.1:{self.screen.port}/{self.screen.token}/"))
            elif url:
                steps.configure(text="1.  Connect the phone or tablet to the same Wi-Fi as this PC.\n"
                                     "2.  Scan the code with its camera, or type the address into its browser.\n"
                                     "3.  Start coaching. Tip: add the page to the home screen for full screen.")
                try:
                    import segno
                    m = [list(row) for row in segno.make(url, error="m").matrix]
                    cell, pad = max(4, 232 // (len(m) + 8)), 4
                    size = (len(m) + 2 * pad) * cell
                    qr.configure(width=size, height=size)
                    qr.delete("all")
                    for y, row in enumerate(m):
                        for x, v in enumerate(row):
                            if v:
                                qr.create_rectangle((x + pad) * cell, (y + pad) * cell, (x + pad + 1) * cell,
                                                    (y + pad + 1) * cell, fill="black", outline="")
                    qr.pack(pady=(12, 8))
                except Exception:
                    pass                              # no QR code part installed yet: the address still works
                addr.configure(state="normal")
                addr.delete(0, "end")
                addr.insert(0, url)
                addr.configure(state="readonly")
                addr.pack(pady=(4, 6), ipady=6)
                others = [f"http://{ip}:{self.screen.port}/{self.screen.token}/" for ip in other_lan_ips()]
                note.configure(text="Page doesn't load? The first time, Windows asks to allow SimCoach on private "
                                    "networks: choose Allow. The phone must be on the same Wi-Fi (not mobile data or "
                                    "a guest network). The address is private to you: it stays the same until you "
                                    "reinstall."
                                    + (" This PC has more than one network address; if that one doesn't work, try "
                                       + " or ".join(others) + "." if others else ""))
                onoff.configure(text="Turn off", command=lambda: set_on(False))
                copy_b.configure(state="normal", command=lambda: (self.root.clipboard_clear(),
                                                                  self.root.clipboard_append(url)))
                test_b.configure(state="normal", command=lambda: self._open(
                    f"http://127.0.0.1:{self.screen.port}/{self.screen.token}/"))
            else:
                failed = bool(self.cfg.get("second_screen"))
                steps.configure(text=(f"Couldn't start it: port {self.cfg.get('second_screen_port', 8765)} is in use "
                                      f"by another program. Close that program, or change second_screen_port in "
                                      f"SimCoach's config.json, then turn it on again." if failed else
                                      "It's off. Turn it on to get the address and a code to scan."))
                note.configure(text="")
                onoff.configure(text="Turn on", command=lambda: set_on(True))
                copy_b.configure(state="disabled")
                test_b.configure(state="disabled")
            note.pack(anchor="w", pady=(4, 0))
            btns.pack_forget()
            btns.pack(fill="x", pady=(14, 0))
        onoff.pack(side="left")
        copy_b.pack(side="left", padx=8)
        test_b.pack(side="left")
        ttk.Button(btns, text="Close", command=close).pack(side="right")
        dlg.protocol("WM_DELETE_WINDOW", close)
        if not self.cfg.get("second_screen"):
            set_on(True)                              # opening this is asking for it
        else:
            self._apply_second_screen()
            show()

    def _apply_second_screen(self):
        if self.cfg.get("second_screen"):
            self.screen.start(self.cfg.get("second_screen_port", 8765))
        else:
            self.screen.stop()
        if hasattr(self, "screen_lbl"):
            self.screen_lbl.configure(text=(f"Open {self.screen.url()} on your phone (same Wi-Fi)"
                                            if self.screen.running() else ""))

    def _btn_repeat(self):
        self.voice.say(self.voice.last_text or "Nothing to repeat yet.", time.monotonic(), "urgent")

    def _btn_mute(self):
        muted = self.cfg.get("talk_level", 1) != 0
        self.cfg["talk_level"] = 0 if muted else max(1, self.talk_pref)
        self.post(mute=muted)
        self.voice.say("Coach muted. Answers only." if muted else "Coach back on.", time.monotonic(), "urgent")

    def _btn_tones(self):
        on = self.cfg.get("brake_callouts", "focus") != "off"
        self.cfg["brake_callouts"] = "off" if on else "focus"
        self.post(tones=self.cfg["brake_callouts"])
        self.voice.say("Braking tones off." if on else "Braking tones on.", time.monotonic(), "urgent")

    def _btn_capture(self):
        msg = self.coach.capture.toggle()
        self.log(msg)
        self.voice.say(msg, time.monotonic(), "urgent")

    def _sheet_open(self):
        return self.sheet_win is not None and self.sheet_win.alive()

    def _close_sheet(self):
        if self.sheet_win is not None:
            self.sheet_win.close()
        self.sheet_win = None

    def show_setup_sheet(self, sheet=None):
        """Open the setup sheet (the newest one, or the one just made). With none yet, the built-in advisor
        writes one from what SimCoach has seen of this car and track."""
        sheet = sheet or self.coach.last_setup_sheet
        if not sheet:
            if self.coach.last_frame is None:
                self.log("No setup sheet yet. Start coaching and go to the garage, then press Setup sheet "
                         "or say \"suggest a setup\".")
                return
            def make():
                c = self.coach
                c.collaborate_race_setup(c.last_frame, time.monotonic(), speak=False, use_openai=False, show=True)
            threading.Thread(target=make, daemon=True, name="setup-sheet").start()
            return
        self.coach._sheet_wait = None
        self._close_sheet()
        try:
            self.sheet_win = SetupSheetWindow(self.root, sheet, open_file=self._open, font=self._font)
        except Exception as e:
            self.sheet_win = None
            self.log(f"Couldn't open the setup sheet: {type(e).__name__}: {e}")

    def toggle(self):
        self.stop_coach() if self.running else self.start_coach()

    def start_coach(self):
        if self.running:
            return
        self.save_settings(quiet=True)
        self.ensure_listener()
        if self._readers_stale:
            self._close_readers()
        if self.readers is None:
            self.readers = available_readers(self.cfg, log=self.log)
            self.log("Sims supported: " + (", ".join(r.name for r in self.readers) or "none (Windows only)"))
        self.stop = threading.Event()
        self._tel_thread = threading.Thread(target=coach_loop, args=(self.coach, self.readers, self.stop),
                                            daemon=True, name="telemetry")
        self._tel_thread.start()
        self.running = True
        self.start_btn.configure(text="Stop coaching", style="Stop.TButton")
        self._set_status("Waiting for a sim...", C["warn"])

    def ensure_listener(self):
        """Start (or restart, after a model change) the push-to-talk listener. Independent of coaching."""
        if not self.mic_on:
            return
        if self.listener is None or self.listener.model_name != self.cfg.get("whisper_model"):
            if self.listener is not None:
                self.listener.stop.set()
            self.listener = Listener(self.cfg, self.voice, self.controls, self.conv.handle, log=self.log,
                                     events=self.post)

    def stop_coach(self):
        if self.stop:
            self.stop.set()
        th = getattr(self, "_tel_thread", None)
        if th is not None and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=1.0)
        self._tel_thread = None
        path = self.coach.end_session()
        with self.coach.lock:
            self.coach.key = None
            self.coach.frame_mono = 0.0
        self.coach.clear_delta()
        if self.coach.crew is not None:
            self.coach.crew.key = None
        if path:
            self.log(f"Report saved: {path}")
            self.load_reports()
            self.load_refs()
        self.running = False
        self.start_btn.configure(text="Start coaching", style="Accent.TButton")
        self._set_status("Not running", C["mut"])

    def _set_status(self, text, color):
        self.status_lbl.configure(text=text, foreground=C["mut"] if color == C["mut"] else C["fg"])
        self.dot.itemconfigure(self.dot_id, fill=color)

    def test_voice(self):
        self.save_settings(quiet=True)
        name = self.cfg.get("driver_name") or "driver"
        self.voice.say(f"Radio check, {name}. Loud and clear.", time.monotonic(), "urgent")

        def tones():
            time.sleep(2.6)
            for f_, ms in ((760, 80), (760, 80), (1250, 150)):
                self.voice.tone(f_, ms)
                time.sleep(0.5)
        threading.Thread(target=tones, daemon=True).start()

    def test_crew(self):
        """One line from each crew member in their own voice (uses the voices picked in Settings)."""
        self.save_settings(quiet=True)
        lines = {"engineer": "Engineer on the radio. I'll keep you posted on fuel, tyres and damage.",
                 "strategist": "Strategist here. Positions, gaps and the plan, every lap.",
                 "spotter": "Spotter's up in the stand. Car left."}
        crew, now = self.coach.crew, time.monotonic()
        for role, _label, _v in CREW_ROLES:
            if crew.on(role):
                self.voice.say(lines[role], now, "urgent", voice=crew.voice_for(role), who=role.upper())

    def _ai_status(self):
        if ai_key(self.cfg):
            return ai_label(self.cfg)
        return f"No {AI_PROVIDERS[ai_provider(self.cfg)]['name']} key yet: commands work, questions need a key (Settings)"

    def test_key(self):
        pid = _AI_BY_LABEL.get(self.vars["ai_provider"].get(), "openai")
        key = (self.vars[f"{pid}_api_key"].get().strip() or os.environ.get(AI_PROVIDERS[pid]["env"]) or "").strip()
        model = (self.vars[f"{pid}_model"].get() or DEFAULT_CONFIG[f"{pid}_model"]).strip()
        if not key:
            self.key_lbl.configure(text="Paste a key first.")
            return
        self.key_lbl.configure(text="Testing…")

        def work():
            try:
                reply = openai_chat(key, model, [{"role": "user", "content": "Reply with the word OK."}], max_tokens=16,
                                    provider=pid)
                self.post(keytest=f"Key works with {model} ✓" if reply else "Connected, but the model sent no reply")
            except Exception as e:
                self.log(f"Key test failed: {type(e).__name__}: {e}")
                self.post(keytest=openai_problem(e, pid).replace(" Check it in Settings.", ""))
        threading.Thread(target=work, daemon=True, name="test-ai-key").start()

    def refresh_devices(self):
        def work():
            outs = self.voice.list_outputs()
            mics = list_input_devices()
            self.post(devices=(outs, mics))
        threading.Thread(target=work, daemon=True).start()

    def _ptt(self, down):
        if down:
            self.ensure_listener()
        if self.listener is None:
            return
        (self.listener.gui_ptt.set if down else self.listener.gui_ptt.clear)()
        for b in (self.talk_btn, self.rc_talk_btn):
            b.configure(text="Listening..." if down else "Hold to talk")

    def _mute_changed(self):
        self.cfg["talk_level"] = 0 if self.mute_var.get() else max(1, self.talk_pref)

    def bind_action(self, action):
        self.bind_lbls[action].configure(text="Press the wheel button now…")
        if not self.controls.ok:
            self.bind_lbls[action].configure(text="No wheel found (is it plugged in?)")
            return

        def got(b):
            if b:
                self.controls.bind(action, b)
            self.post(bindings=True)
        self.controls.capture(got, timeout=20)

    def clear_action(self, action):
        self.controls.bind(action, None)
        self.post(bindings=True)

    def make_shortcut(self):
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            lnk = shell.CreateShortCut(os.path.join(shell.SpecialFolders("Desktop"), "SimCoach.lnk"))
            exe = os.path.join(SCRIPT_DIR, "SimCoach.exe")
            ico = os.path.join(SCRIPT_DIR, "SimCoach.ico")
            if os.path.exists(exe):
                lnk.TargetPath = exe
            else:
                lnk.TargetPath = os.path.join(SCRIPT_DIR, "SimCoach.bat")
                lnk.WindowStyle = 7
            if os.path.exists(ico):
                lnk.IconLocation = ico + ",0"
            lnk.WorkingDirectory = SCRIPT_DIR
            lnk.Description = "SimCoach - live voice coach"
            lnk.Save()
            self.saved_lbl.configure(text="Desktop shortcut created.")
        except Exception as e:
            self.saved_lbl.configure(text=f"Couldn't create shortcut: {e}")

    def save_settings(self, quiet=False):
        v = self.vars
        old_audio = (self.cfg.get("audio_out"), self.cfg.get("volume"))
        self.cfg["driver_name"] = v["driver_name"].get().strip()
        self.cfg["voice"] = _VOICE_BY_LABEL.get(v["voice"].get(), self.cfg["voice"])
        self.cfg["speech_rate"] = int(round(float(v["speech_rate"].get())))
        self.cfg["volume"] = round(float(v["volume"].get()), 2)
        out = v["audio_out"].get()
        self.cfg["audio_out"] = "" if out == "Windows default" else out
        mic = v["mic"].get()
        self.cfg["mic"] = "" if mic == "Windows default" else mic
        self.cfg["talk_level"] = self.talk_pref = int(v["talk_level"].get())
        self.cfg["coach_personality"] = _PERSONALITY_BY_LABEL.get(v["coach_personality"].get(), DEFAULT_CONFIG["coach_personality"])
        self.cfg["brake_callouts"] = v["brake_callouts"].get()
        self.cfg["split_callouts"] = bool(v["split_callouts"].get())
        self.cfg["auto_start"] = bool(v["auto_start"].get())
        self.cfg["starter_laps"] = bool(v["starter_laps"].get())
        self.cfg["shared_refs"] = bool(v["shared_refs"].get())
        for role, _label, _dv in CREW_ROLES:
            self.cfg[f"{role}_on"] = bool(v[f"{role}_on"].get())
            self.cfg[f"{role}_voice"] = _VOICE_BY_LABEL.get(v[f"{role}_voice"].get(), _dv)
        self.cfg["spotter_swap"] = [g for g in SPOTTER_GAMES if v[f"swap_{g}"].get()]
        self.cfg["crew_updates"] = _UPDATES_BY_LABEL.get(v["crew_updates"].get(), DEFAULT_CONFIG["crew_updates"])
        self.cfg["crew_chatter"] = _CHATTER_BY_LABEL.get(v["crew_chatter"].get(), "normal")
        self.cfg["crew_language"] = _LANGUAGE_BY_LABEL.get(v["crew_language"].get(), "clean")
        self.cfg["briefing_mode"] = dict(BRIEFING_MODES).get(v["briefing_mode"].get(), "daily")
        self.cfg["sheet_autopop"] = bool(v["sheet_autopop"].get())
        self.cfg["udp_share_simhub"] = bool(v["udp_share_simhub"].get())
        self.cfg["second_screen"] = bool(v["second_screen"].get())
        self.cfg["check_updates"] = bool(v["check_updates"].get())
        _UDPPort.share = self.cfg["udp_share_simhub"]
        self.cfg["whisper_model"] = _WHISPER_BY_LABEL.get(v["whisper_model"].get(), "small.en")
        self.cfg["ai_provider"] = _AI_BY_LABEL.get(v["ai_provider"].get(), "openai")
        self.cfg["ai_fallback"] = bool(v["ai_fallback"].get())
        for pid in AI_PROVIDERS:
            self.cfg[f"{pid}_api_key"] = v[f"{pid}_api_key"].get().strip() or DEFAULT_CONFIG[f"{pid}_api_key"]
            self.cfg[f"{pid}_model"] = (v[f"{pid}_model"].get() or DEFAULT_CONFIG[f"{pid}_model"]).strip()
        old_f1_port = self.cfg.get("f1_port", 20777)
        try:
            p_f1 = int(v["f1_port"].get())
            if 1 <= p_f1 <= 65535:
                self.cfg["f1_port"] = p_f1
        except ValueError:
            pass
        if self.cfg.get("f1_port") != old_f1_port and self.readers is not None:
            if self.running:
                self._readers_stale = True
                self.log("New F1 port is used the next time you press Start coaching.")
            else:
                self._close_readers()
        save_config(self.cfg)
        self._apply_second_screen()
        if self.mute_var.get():
            self.cfg["talk_level"] = 0
        if (self.cfg.get("audio_out"), self.cfg.get("volume")) != old_audio:
            self.voice.reconfigure()
        if hasattr(self, "rc_info"):
            self.rc_info["ai"].configure(text=self._ai_status())
            self.rc_info["ptt"].configure(text=self.controls.describe("ptt") + "\nor F8 / the button below")
        if not quiet:
            self.saved_lbl.configure(text="Saved.")
            self.root.after(2500, lambda: self.saved_lbl.configure(text=""))

    def load_reports(self, select=None):
        tv = self.rep_tv
        tv.delete(*tv.get_children())
        d = ensure_report_dir()
        rows = []
        try:
            for f in os.listdir(d):
                is_txt = f.endswith("_after_race.txt")
                is_sheet = f.endswith("_setup.txt")
                if not (f.endswith(".html") or is_txt or is_sheet):
                    continue
                m = _RE_REPORT_FILE.match(f)
                if m:
                    date, name = f"{m.group(1)} {m.group(2)}:{m.group(3)}", m.group(4)
                else:
                    date = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(os.path.join(d, f))))
                    name = f[:-len("_after_race.txt")] if is_txt else f[:-len("_setup.txt")] if is_sheet else f[:-5]
                name = name.replace("_", " ") + ("  (after-race report, text)" if is_txt else
                                                 "  (race setup sheet, text)" if is_sheet else "")
                rows.append((date, f, name))
        except Exception as e:
            self._rep_note(f"Can't read the reports folder: {e}")
        for date, f, name in sorted(rows, reverse=True):
            tv.insert("", "end", iid=f, values=(date, name))
        kids = tv.get_children()
        pick = select if select in kids else (kids[0] if kids else None)
        if pick:
            tv.selection_set(pick)
            tv.see(pick)
        self._rep_note(f"{len(kids)} report{'s' if len(kids) != 1 else ''} in {d}" if kids else
                       "No reports yet. They're written when a session ends, or with Write report now.")

    def _rep_note(self, text):
        if hasattr(self, "rep_status"):
            self.rep_status.configure(text=text)

    def _selected_report(self):
        sel = self.rep_tv.selection() or self.rep_tv.get_children()[:1]
        return os.path.join(REPORT_DIR, sel[0]) if sel else None

    def open_report(self):
        path = self._selected_report()
        if path:
            self._open(path)
        else:
            self._rep_note("No reports yet.")

    def write_report_now(self):
        path = self.coach.snapshot_report()
        if path:
            self.load_reports(select=os.path.basename(path))
            self._rep_note(f"Written: {os.path.basename(path)}")
            self._open(path)
        else:
            self._rep_note("Need at least one counted lap this session first.")

    def delete_report(self):
        path = self._selected_report()
        if not path:
            return
        from tkinter import messagebox
        if not messagebox.askyesno("Delete report", f"Delete {os.path.basename(path)}?", parent=self.root):
            return
        try:
            os.remove(path)
            self._rep_note(f"Deleted {os.path.basename(path)}")
        except Exception as e:
            self._rep_note(f"Couldn't delete: {e}")
        self.load_reports()

    OV_KEY = "#010203"
    _VERDICT = {"much": ("TOO MUCH", "bad"), "little": ("TOO LITTLE", "warn"), "enough": ("ENOUGH", "good"),
                "idle": ("OFF", "mut"), "none": ("NO REF", "mut")}

    def toggle_overlay(self):
        if self.overlay_win is not None:
            self._ov_close()
            return
        tk = self.tk
        w = self.overlay_win = tk.Toplevel(self.root)
        w.title("SimCoach overlay")
        w.protocol("WM_DELETE_WINDOW", self._ov_close)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=self.OV_KEY)
        for attr, val in (("-transparentcolor", self.OV_KEY), ("-alpha", 0.93)):
            try:
                w.attributes(attr, val)
            except Exception:
                pass
        self.ov_meter = PedalMeter()
        self._ov_idle = False
        self._ov_build()
        x, y = self._ov_onscreen(*(self.cfg.get("overlay_pos") or [40, 40])[:2])
        w.geometry(f"+{x}+{y}")
        self.ov_cv.bind("<ButtonPress-1>", self._ov_drag_start)
        self.ov_cv.bind("<B1-Motion>", self._ov_drag)
        self.ov_cv.bind("<ButtonRelease-1>", self._ov_drag_end)
        self.ov_cv.bind("<Button-3>", self._ov_menu)
        self._ov_tick()
        if self.cfg.get("overlay_locked"):
            self.root.after(60, self._ov_apply_lock)

    def toggle_overlay_lock(self):
        """Lock: the overlay lets every click through to the game and never takes focus. A locked overlay can't
        be right-clicked, so this button on the main window (or the overlay menu before locking) switches it."""
        locked = self.cfg["overlay_locked"] = not bool(self.cfg.get("overlay_locked"))
        save_config(self.cfg)
        self._ov_apply_lock()
        try:
            self.ov_lock_btn.configure(text="Unlock overlay" if locked else "Lock overlay")
        except Exception:
            pass
        self.log("Overlay locked: clicks go through to the game. Unlock it with the button up top."
                 if locked else "Overlay unlocked: drag it anywhere, right-click it for options.")

    def _ov_apply_lock(self, user32=None):
        """Windows: WS_EX_TRANSPARENT (+ WS_EX_LAYERED, which Tk already sets for the see-through corners) passes
        clicks through; WS_EX_NOACTIVATE keeps the game focused. Its own user32 handle, so the argtypes set here
        don't touch any other ctypes caller."""
        if self.overlay_win is None:
            return False
        ct = ctypes
        if user32 is None:
            if sys.platform != "win32" or ct is None:
                return False
            try:
                user32 = ct.WinDLL("user32", use_last_error=True)
            except Exception:
                return False
        elif ct is None:
            import ctypes as ct
        locked = bool(self.cfg.get("overlay_locked"))
        try:
            vp, ssz = ct.c_void_p, ct.c_ssize_t
            anc = user32.GetAncestor
            anc.restype, anc.argtypes = vp, (vp, ct.c_uint)
            hwnd = anc(self.overlay_win.winfo_id(), 2)
            if not hwnd:
                return False
            get = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
            put = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
            get.restype, get.argtypes = ssz, (vp, ct.c_int)
            put.restype, put.argtypes = ssz, (vp, ct.c_int, ssz)
            ex = get(hwnd, -20)
            bits = 0x20 | 0x08000000
            new = (ex | 0x80000 | bits) if locked else (ex & ~bits)
            if new != ex:
                put(hwnd, -20, new)
                swp = user32.SetWindowPos
                swp.restype = ct.c_int
                swp.argtypes = (vp, vp, ct.c_int, ct.c_int, ct.c_int, ct.c_int, ct.c_uint)
                swp(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
            return True
        except Exception as e:
            self.log(f"Couldn't {'lock' if locked else 'unlock'} the overlay: {e}")
            return False

    def _ov_onscreen(self, x, y):
        """The saved spot, if it's still on a monitor (the overlay has no title bar to drag it back);
        otherwise the top-left corner of the main screen."""
        try:
            x, y = int(x), int(y)
        except (TypeError, ValueError):
            return 40, 40
        if sys.platform == "win32" and ctypes is not None:
            try:
                class _PT(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
                mfp = ctypes.windll.user32.MonitorFromPoint
                mfp.restype = ctypes.c_void_p
                if mfp(_PT(x + 40, y + 20), 0):
                    return x, y
                return 40, 40
            except Exception:
                pass
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        return (x, y) if (-20 <= x <= sw - 80 and -20 <= y <= sh - 40) else (40, 40)

    def _ov_close(self):
        ov_after = getattr(self, "_ov_after", None)
        if ov_after is not None:
            try:
                self.root.after_cancel(ov_after)
            except Exception:
                pass
            self._ov_after = None
        if self.overlay_win is not None:
            try:
                self.overlay_win.destroy()
            except Exception:
                pass
        self.overlay_win = None

    @staticmethod
    def _round_rect(cv, x0, y0, x1, y1, r, **kw):
        r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
               x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return cv.create_polygon(pts, smooth=True, **kw)

    def _ov_build(self):
        tk = self.tk
        self._ov_idle = False
        pedals = bool(self.cfg.get("overlay_pedals", True))
        W, H = (620, 248) if pedals else (380, 150)
        if getattr(self, "ov_cv", None) is not None and self.ov_cv.winfo_exists():
            self.ov_cv.destroy()
        cv = self.ov_cv = tk.Canvas(self.overlay_win, width=W, height=H, bg=self.OV_KEY, highlightthickness=0, bd=0)
        cv.pack()
        self._round_rect(cv, 1, 1, W - 1, H - 1, 18, fill=C["bg"], outline=C["line"], width=1)
        cv.create_text(18, 16, text="SIMCOACH", anchor="w", fill=C["mut"], font=self._font(8, True))
        bx1 = 362                                     # right edge of the delta / tip column, clear of the gauges
        self._round_rect(cv, bx1 - 62, 6, bx1, 26, 10, fill=C["panel2"], outline=C["line"], tags=("setup_btn",))
        cv.create_text(bx1 - 31, 16, text="SETUP", fill=C["fg"], font=self._font(8, True), tags=("setup_btn",))
        self.ov_delta = cv.create_text(18, 30, text=self.delta_lbl.cget("text"), anchor="nw",
                                       fill=self.delta_lbl.cget("fg"), font=self._font(30, True))
        tip0 = self.tip_lbl.cget("text")
        self.ov_tip = cv.create_text(18, 84, text="" if tip0 == "—" else tip0, anchor="nw", fill=C["tip"],
                                     font=self._font(11), width=344)
        self.ov_g = {}
        if not pedals:
            return
        tx0, ty0, tx1, ty1 = 18, 150, 362, 232
        self._round_rect(cv, tx0, ty0, tx1, ty1, 10, fill=C["panel"], outline=C["line"])
        cv.create_text(tx0 + 10, ty0 + 10, text="PEDAL TRACE  ·  dashed = best lap", anchor="w",
                       fill=C["mut"], font=self._font(7, True))
        self._ov_trace_box = (tx0 + 8, ty0 + 20, tx1 - 8, ty1 - 8)
        self.ov_lines = {
            "ref_thr": cv.create_line(0, 0, 0, 0, fill="#1f6f5a", width=2, dash=(4, 3), state="hidden"),
            "ref_brk": cv.create_line(0, 0, 0, 0, fill="#8a3434", width=2, dash=(4, 3), state="hidden"),
            "thr": cv.create_line(0, 0, 0, 0, fill=C["good"], width=2, state="hidden"),
            "brk": cv.create_line(0, 0, 0, 0, fill=C["bad"], width=2, state="hidden"),
        }
        self._ov_hidden = set(self.ov_lines.values())
        self._ov_xs_key = None
        for k, (key, label) in enumerate((("brk", "BRAKE"), ("thr", "THROTTLE"))):
            gx = 392 + k * 112
            gy0, gy1 = 34, 178
            cv.create_text(gx + 24, 16, text=label, fill=C["mut"], font=self._font(8, True))
            track = self._round_rect(cv, gx, gy0, gx + 48, gy1, 14, fill=C["panel2"], outline=C["line"], width=2)
            for q in (0.25, 0.5, 0.75):
                yq = gy1 - q * (gy1 - gy0)
                cv.create_line(gx + 52, yq, gx + 58, yq, fill=C["line"])
            band = cv.create_rectangle(gx + 3, gy1, gx + 45, gy1, fill="#26364a", outline="", state="hidden")
            fill = self._round_rect(cv, gx + 4, gy1 - 4, gx + 44, gy1 - 4, 10, fill=C["acc"], outline="")
            band_ol = cv.create_rectangle(gx + 2, gy1, gx + 46, gy1, outline="#e6edf3", dash=(3, 2), state="hidden")
            meniscus = cv.create_line(gx + 6, gy1, gx + 42, gy1, fill="#ffffff", width=2)
            arrow = cv.create_polygon(0, 0, 0, 0, 0, 0, fill=C["fg"], state="hidden")
            pct = cv.create_text(gx + 24, 194, text="0%", fill=C["fg"], font=self._font(13, True))
            pill = self._round_rect(cv, gx - 14, 210, gx + 62, 234, 12, fill=C["panel2"], outline="")
            ptxt = cv.create_text(gx + 24, 222, text="NO REF", fill=C["mut"], font=self._font(8, True))
            self.ov_g[key] = {"x": gx, "y0": gy0, "y1": gy1, "track": track, "band": band, "band_ol": band_ol,
                              "fill": fill, "men": meniscus, "arrow": arrow, "pct": pct, "pill": pill, "ptxt": ptxt,
                              "sig": None}

    def _ov_set_text(self, delta=None, color=None, tip=None):
        if self.overlay_win is None:
            return
        try:
            if delta is not None:
                self.ov_cv.itemconfigure(self.ov_delta, text=delta, fill=color or C["fg"])
            if tip is not None:
                self.ov_cv.itemconfigure(self.ov_tip, text=tip)
        except Exception:
            pass

    def _ov_tick(self):
        if self.overlay_win is None:
            return
        try:
            if self.ov_g:
                c = self.coach
                st = None
                if c.last_frame is not None and not c.live():
                    if not self._ov_idle:
                        self._ov_idle = True
                        for key in ("brk", "thr"):
                            self._ov_gauge(key, {"value": 0.0, "band": None, "verdict": "idle", "flag": None}, False)
                        self.ov_meter._last_frame = None
                else:
                    self._ov_idle = False
                    st = self.ov_meter.update(c.last_frame, c.ref, c.track_len)
                if st is not None:
                    flash = int(time.monotonic() * 7) % 2 == 0
                    for key in ("brk", "thr"):
                        self._ov_gauge(key, st[key], flash)
                    self._ov_trace()
        except Exception as e:
            self.log(f"Overlay error: {e}")
        delay = 100 if (getattr(self, "_ov_idle", False) or not self.ov_g) else 33
        self._ov_after = self.root.after(delay, self._ov_tick)

    def _ov_gauge(self, key, g, flash):
        G, cv = self.ov_g[key], self.ov_cv
        x, y0, y1 = G["x"], G["y0"] + 4, G["y1"] - 4
        val, band, verdict, flag = g["value"], g["band"], g["verdict"], g["flag"]
        word, ck = self._VERDICT[verdict]
        if flag:
            word = "LOCK-UP" if flag == "lock" else "WHEELSPIN"
        col = C[ck] if verdict not in ("idle", "none") else C["acc"]
        sig = (round(val, 2), band and (round(band[0], 2), round(band[1], 2)), verdict, flag, flash if flag else None)
        if sig == G["sig"]:
            return
        G["sig"] = sig
        yv = y1 - val * (y1 - y0)
        cv.coords(G["fill"], *self._rr_pts(x + 4, min(yv, y1 - 2), x + 44, y1, 10))
        cv.itemconfigure(G["fill"], fill=col)
        cv.coords(G["men"], x + 6, yv, x + 42, yv)
        if band is not None and band[1] > 0.02:
            ya, yb = y1 - band[1] * (y1 - y0), y1 - band[0] * (y1 - y0)
            cv.coords(G["band"], x + 3, ya, x + 45, max(yb, ya + 3))
            cv.coords(G["band_ol"], x + 2, ya, x + 46, max(yb, ya + 3))
            cv.itemconfigure(G["band"], state="normal")
            cv.itemconfigure(G["band_ol"], state="normal")
            cv.tag_lower(G["band"], G["fill"])
        else:
            cv.itemconfigure(G["band"], state="hidden")
            cv.itemconfigure(G["band_ol"], state="hidden")
        if verdict in ("much", "little"):
            ax = x + 60
            if verdict == "much":
                pts = (ax, yv - 8, ax + 14, yv - 8, ax + 7, yv + 6)
            else:
                pts = (ax, yv + 8, ax + 14, yv + 8, ax + 7, yv - 6)
            cv.coords(G["arrow"], *pts)
            cv.itemconfigure(G["arrow"], fill=col, state="normal")
        else:
            cv.itemconfigure(G["arrow"], state="hidden")
        cv.itemconfigure(G["track"], outline=(C["bad"] if flash else "#ffffff") if flag else C["line"])
        cv.itemconfigure(G["pct"], text=f"{val * 100:.0f}%")
        cv.itemconfigure(G["pill"], fill=col if verdict not in ("idle", "none") else C["panel2"])
        cv.itemconfigure(G["ptxt"], text=word, fill="#0b0f14" if verdict not in ("idle", "none") else C["mut"])

    @staticmethod
    def _rr_pts(x0, y0, x1, y1, r):
        r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
        return (x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
                x0, y1, x0, y1 - r, x0, y0 + r, x0, y0)

    def _ov_trace(self):
        h = self.ov_meter.hist
        nh = len(h)
        if nh < 2:
            return
        cv, L = self.ov_cv, self.ov_lines
        x0, y0, x1, y1 = self._ov_trace_box
        key = (nh, x0, x1)
        if getattr(self, "_ov_xs_key", None) != key:
            n = h.maxlen or nh
            dx = (x1 - x0) / (n - 1)
            start = x1 - dx * (nh - 1)
            self._ov_xs, self._ov_xs_key = [start + dx * k for k in range(nh)], key
        xs, span = self._ov_xs, y1 - y0
        smp = list(h)
        has_ref = self.coach.ref is not None
        for idx, name in ((0, "thr"), (1, "brk"), (2, "ref_thr"), (3, "ref_brk")):
            if idx >= 2 and not has_ref:
                if L[name] not in self._ov_hidden:
                    cv.itemconfigure(L[name], state="hidden")
                    self._ov_hidden.add(L[name])
                continue
            pts = []
            for x, s_ in zip(xs, smp):
                v = s_[idx]
                if v is not None:
                    pts.append(x)
                    pts.append(y1 - v * span)
            if len(pts) >= 4:
                cv.coords(L[name], pts)
                if L[name] in self._ov_hidden:
                    cv.itemconfigure(L[name], state="normal")
                    self._ov_hidden.discard(L[name])
            elif L[name] not in self._ov_hidden:
                cv.itemconfigure(L[name], state="hidden")
                self._ov_hidden.add(L[name])

    def _ov_drag_start(self, e):
        self._ov_drag0 = (e.x_root - self.overlay_win.winfo_x(), e.y_root - self.overlay_win.winfo_y())
        try:
            hit = "setup_btn" in self.ov_cv.gettags("current")
        except Exception:
            hit = False
        self._ov_press = (e.x_root, e.y_root) if hit else None

    def _ov_drag(self, e):
        dx, dy = getattr(self, "_ov_drag0", (0, 0))
        self.overlay_win.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

    def _ov_drag_end(self, e):
        press, self._ov_press = getattr(self, "_ov_press", None), None
        if press is not None and e is not None and abs(e.x_root - press[0]) + abs(e.y_root - press[1]) < 6:
            self.post(setup_toggle=True)       # a tap on SETUP (a drag that starts on it still moves the overlay)
            return
        self.cfg["overlay_pos"] = [self.overlay_win.winfo_x(), self.overlay_win.winfo_y()]
        save_config(self.cfg)

    def _ov_reset_pos(self):
        # winfo_x/y still report the old place until Tk redraws, so save the new spot directly.
        self.overlay_win.geometry("+40+40")
        self.cfg["overlay_pos"] = [40, 40]
        save_config(self.cfg)

    def _ov_menu(self, e):
        tk = self.tk
        m = tk.Menu(self.overlay_win, tearoff=0, bg=C["panel2"], fg=C["fg"], activebackground=C["acc"],
                    activeforeground="#ffffff", bd=0)
        on = bool(self.cfg.get("overlay_pedals", True))
        m.add_command(label="Show / hide setup sheet", command=lambda: self.post(setup_toggle=True))
        m.add_command(label=("Hide" if on else "Show") + " pedal gauges", command=self._ov_toggle_pedals)
        m.add_command(label="Reset position", command=self._ov_reset_pos)
        if sys.platform == "win32":
            m.add_command(label="Lock (clicks go through to the game)", command=self.toggle_overlay_lock)
        m.add_separator()
        m.add_command(label="Close overlay", command=self._ov_close)
        m.tk_popup(e.x_root, e.y_root)

    def _ov_toggle_pedals(self):
        self.cfg["overlay_pedals"] = not bool(self.cfg.get("overlay_pedals", True))
        save_config(self.cfg)
        self._ov_build()
        self.ov_meter._last_frame = None
        self.ov_cv.bind("<ButtonPress-1>", self._ov_drag_start)
        self.ov_cv.bind("<B1-Motion>", self._ov_drag)
        self.ov_cv.bind("<ButtonRelease-1>", self._ov_drag_end)
        self.ov_cv.bind("<Button-3>", self._ov_menu)

    def quit(self):
        try:
            self.screen.stop()
        except Exception:
            pass
        if self.listener is not None:
            self.listener.stop.set()
        if self.running:
            self.stop_coach()
        self._close_readers()
        self.root.destroy()

    def _close_readers(self):
        for r_ in self.readers or ():
            try:
                r_.close()
            except Exception:
                pass
        self.readers = None
        self._readers_stale = False

    _RE_PRETTY_TIME = re.compile(r"\b(\d+) (\d\d\.\d)\b")

    @classmethod
    def _pretty(cls, text):
        return cls._RE_PRETTY_TIME.sub(r"\1:\2", text).replace("k p h", "km/h")

    def _pump(self):
        merged, sheet_events = {}, []
        try:
            for _ in range(200):
                kw = self.inbox.get_nowait()
                if any(k.startswith("rc_") for k in kw):
                    self._rc_event(kw)
                if any(k in kw for k in ("setup_sheet", "setup_close", "setup_toggle")):
                    sheet_events.append(kw)
                merged.update(kw)
        except queue.Empty:
            pass
        if merged:
            if "delta" in merged:
                col = merged.get("delta_color", C["fg"])
                self.delta_lbl.configure(text=merged["delta"], fg=col)
                self._ov_set_text(delta=merged["delta"], color=col)
            if "tip" in merged:
                tip = self._pretty(merged["tip"])
                self.tip_lbl.configure(text=tip)
                self._ov_set_text(tip=tip)
            if "focus" in merged:
                self.focus_lbl.configure(text=self._pretty(merged["focus"]))
            if "heard" in merged:
                self.heard_lbl.configure(text=merged["heard"])
            if "head" in merged:
                self.head_lbl.configure(text=self._pretty(merged["head"]))
                if self.running and not merged.get("race_finished"):
                    waiting = merged["head"].lower().startswith("waiting")
                    self._set_status("Waiting for a sim..." if waiting else "Connected",
                                     C["warn"] if waiting else C["good"])
            if "race_finished" in merged and merged["race_finished"]:
                st_txt = merged.get("race_finished_status") or "Race finished"
                self._set_status(st_txt, C["good"])
                self._refresh_tables_now(force=True)
            if ("report_ready" in merged and merged["report_ready"]) or "setup_sheet" in merged:
                self.load_reports()
                if "report_ready" in merged and merged["report_ready"]:
                    self.load_refs()
            if "mute" in merged:
                self.mute_var.set(bool(merged["mute"]))
            if "talk" in merged:
                self.talk_pref = merged["talk"]
                self.vars["talk_level"].set(merged["talk"])
            if "tones" in merged:
                self.vars["brake_callouts"].set(merged["tones"])
            if "splits" in merged:
                self.vars["split_callouts"].set(bool(merged["splits"]))
            if "persona" in merged and "coach_personality" in self.vars:
                lbl = _LABEL_BY_PERSONALITY.get(merged["persona"])
                if lbl:
                    self.vars["coach_personality"].set(lbl)
            if merged.get("ov_cmd") == "toggle":
                self.toggle_overlay()
            if "bindings" in merged:
                for a, lbl in self.bind_lbls.items():
                    lbl.configure(text=self.controls.describe(a))
            if "keytest" in merged:
                self.key_lbl.configure(text=merged["keytest"])
            if "gh_signed_in" in merged:
                self._gh_signed_in(merged["gh_signed_in"])
            if "gh_error" in merged:
                self.best_lbl.configure(text=merged["gh_error"])
            if "best_shared" in merged:
                self._best_shared(merged["best_shared"])
            if "lib_index" in merged:
                self._lib_index, verdicts = merged["lib_index"]
                if verdicts:
                    shared = self.cfg.get("shared_laps") or {}
                    for n, v in verdicts.items():
                        if n in shared:
                            shared[n]["verdict"] = v
                    save_config(self.cfg)
                self.load_best()
            if "starter_rows" in merged:
                self._show_starters(merged["starter_rows"])
            if "library_sync" in merged:
                if merged["library_sync"]:
                    self.share_lbl.configure(text=merged["library_sync"])
                self.load_refs()
            if "update" in merged:
                self._show_update(merged["update"])
            if "update_progress" in merged:
                self._update_progress(merged["update_progress"])
            if "update_status" in merged and hasattr(self, "upd_lbl"):
                self.upd_lbl.configure(text=merged["update_status"])
            for ev in sheet_events:
                if ev.get("setup_close") or (ev.get("setup_toggle") and self._sheet_open()):
                    self._close_sheet()
                elif ev.get("setup_toggle"):
                    self.show_setup_sheet()
                elif ev.get("setup_sheet") and ev.get("setup_popup"):
                    self.show_setup_sheet(ev["setup_sheet"])
                elif ev.get("setup_sheet") and self._sheet_open() and self.sheet_win.sheet is ev.get("setup_sheet"):
                    self.sheet_win.sync_from_sheet()
            if "devices" in merged:
                outs, mics = merged["devices"]
                self.out_combo.configure(values=["Windows default"] + outs)
                self.mic_combo.configure(values=["Windows default"] + mics)
        wrote_log = False
        try:
            for _ in range(200):
                line = self.logq.get_nowait()
                tag = "coach" if "COACH" in line else "driver" if "DRIVER" in line else None
                self.log_txt.insert("end", line + "\n", tag)
                wrote_log = True
        except queue.Empty:
            pass
        if wrote_log:
            self.log_txt.see("end")
            if int(self.log_txt.index("end-1c").split(".")[0]) > 3000:
                self.log_txt.delete("1.0", "1000.0")
        if self.listener is not None:
            l_state = self.listener.state
            lv = min(1.0, self.listener.level * 1.6)
            bar_w = int(200 * lv)
            bar_col = C["good"] if lv < 0.9 else C["warn"]
            mic_sig = (l_state, bar_w, bar_col)
            if mic_sig != self._last_mic_ui:
                self._last_mic_ui = mic_sig
                st = {"starting": "Loading speech model…", "ready": "Mic ready",
                      "listening": "Listening…", "error": "Mic unavailable (see Log)"}.get(l_state, "")
                self.mic_lbl.configure(text=st)
                self.rc_state.configure(text=st + ("  (first time downloads it, a minute or two)"
                                                   if l_state == "starting" else ""))
                self.rc_meter.coords(self.rc_bar, 0, 0, bar_w, 14)
                self.rc_meter.itemconfigure(self.rc_bar, fill=bar_col)
        self.root.after(80, self._pump)

    def _refresh_tables(self):
        """The one periodic refresh chain (scheduled once from __init__)."""
        self._refresh_tables_now()
        self.root.after(1000, self._refresh_tables)

    def _refresh_tables_now(self, force=False):
        c = self.coach
        try:
            with c.lock:
                rev = (c.key, len(c.history), c.best_time, len(c.corners), c._state_rev)
            laps_shown = self.nb.select() == str(self.tab_laps)
            if rev == self._last_table_rev and not force:
                return
            if not laps_shown and rev == getattr(self, "_last_kpi_rev", None) and not force:
                return
            self._last_table_rev = rev if laps_shown else None
            self._last_kpi_rev = rev
            if laps_shown:
                s = c.summary()
                best, tb = s.get("best_lap_s"), s.get("theoretical_best_s")
            else:
                s = None
                with c.lock:
                    best = None if c.ref_provisional else c.best_time
                    tb = c.theoretical_best()
            with c.lock:
                hist_snap = [(h["time"], bool(h.get("invalid")), bool(h.get("pit"))) for h in c.history]
            alltimes = [t_ for t_, _, _ in hist_snap]
            if best is None and alltimes:
                clean_t = [t_ for t_, inv, pit in hist_snap if not inv and not pit]
                best = min(clean_t or alltimes)
            self.kpi["last"].configure(text=fmt_time(alltimes[-1]).replace(" ", ":") if alltimes else "—")
            self.kpi["best"].configure(text=fmt_time(best).replace(" ", ":") if best else "—")
            self.kpi["theo"].configure(text=fmt_time(tb).replace(" ", ":") if tb else "—")
            self.kpi["laps"].configure(text=str(len(alltimes)))
            tg = c.target()
            pace = c.pace_pct(best) if (best and tg) else None
            self.kpi["pace"].configure(
                text=(f"{pace:.1f}%  ·  target {fmt_time(tg[0]).replace(' ', ':')}" if pace is not None else
                      f"target {fmt_time(tg[0]).replace(' ', ':')}" if tg else "—"))
            cons = consistency_of([t_ for t_, inv, pit in hist_snap if not inv and not pit])
            self.kpi["cons"].configure(text=f"±{cons['sd']:.2f}s  ·  {cons['label']}" if cons else "—")
            if s is None:
                return
            tv = self.laps_tv
            ref = best or (min(alltimes) if alltimes else 0)
            lap_rows = [(str(n), fmt_time(t_).replace(" ", ":") + (" (pit)" if pit else (" (off track)" if inv else "")),
                         f"{t_ - ref:+.2f}") for n, (t_, inv, pit) in enumerate(hist_snap, 1)]
            if lap_rows != [tuple(map(str, tv.item(i, "values"))) for i in tv.get_children()]:
                tv.delete(*tv.get_children())
                for r_ in lap_rows:
                    tv.insert("", "end", values=r_)
            rows = [(f"Turn {x['turn']}", "" if x.get("last_lap_loss_s") is None else f"{x['last_lap_loss_s']:+.2f}s",
                     f"{x['best_min_speed_kmh']:.0f} km/h", self._pretty(x.get("last_issue") or ""))
                    for x in s.get("corners", [])]
            tv = self.turns_tv
            current = [tv.item(i, "values") for i in tv.get_children()]
            if [tuple(map(str, r)) for r in rows] != [tuple(map(str, r)) for r in current]:
                tv.delete(*tv.get_children())
                for r_ in rows:
                    tv.insert("", "end", values=r_)
        except Exception as e:
            self.log(f"UI refresh error: {e}")

    def run(self):
        self.root.mainloop()




class SimReader(Reader):
    name = "TEST"
    CORNERS = [(0.12, 90), (0.30, 140), (0.47, 70), (0.66, 160), (0.85, 110)]

    def __init__(self, laps=7, seed=1):
        import random
        self.r = random.Random(seed)
        self.laps, self.done = laps, 0
        self.pct, self.cur, self.last, self.fuel = 0.0, 0.0, 0.0, 30.0
        self.new_errors()

    def new_errors(self):
        r = self.r
        self.err = [(max(0, r.gauss(0.002, 0.002)), max(0, r.gauss(3, 4)), max(0, r.gauss(0.001, 0.002))) for _ in self.CORNERS]
        if self.done in (3, 4):
            self.err[2] = (0.012, 12, 0.008)

    def state(self, pct):
        v, b, th, st = 260.0, 0.0, 1.0, 0.0
        for k, (apex, vmin) in enumerate(self.CORNERS):
            eb, ev, et = self.err[k]
            vm = vmin - ev
            bs = apex - 0.03 - eb
            if bs <= pct < apex:
                fr = (pct - bs) / (apex - bs)
                v = min(v, 260 - (260 - vm) * fr ** 0.7); b, th, st = 0.8 * (1 - fr) + 0.1, 0.0, 0.2
            elif apex <= pct < apex + 0.04 + et:
                fr = (pct - apex) / (0.04 + et)
                v = min(v, vm + (260 - vm) * fr); b, th, st = 0.0, (0.4 + 0.6 * fr) if fr > 0.5 else 0.4, 0.15
        return v, b, th, st

    def connected(self):
        return self.done <= self.laps

    def read(self):
        dt = 1 / LOOP_HZ
        if self.done >= self.laps:
            self.done += 1
            fr = Frame("TEST", "Test Ring", "Test Car", self.laps, 0.02, 0.0, 0.0, 0.0, 0.0, 1, 1000.0,
                       0.0, self.last, True, False, self.fuel, 4000.0, [85, 86, 84, 85], 8000.0, [0.0] * 4,
                       [27.0, 27.2, 26.8, 27.1], session="race", position=2, cars=16, race_laps=self.laps,
                       gap_ahead=1.4, gap_behind=0.8, race_over=True,
                       car_ahead={"name": "Max Verstappen", "position": 1, "car": "Red Bull RB21", "distance_m": 42, "gap_s": 1.4},
                       car_behind={"name": "Lando Norris", "position": 3, "car": "McLaren MCL39", "distance_m": 24, "gap_s": 0.8})
            return fr
        v, b, th, st = self.state(self.pct)
        self.pct += (v / 3.6) * dt / 4000.0
        self.cur += dt
        self.fuel -= 0.0004
        if self.pct >= 1.0:
            self.pct -= 1.0
            self.done += 1
            self.last, self.cur = self.cur, 0.0
            self.new_errors()
        wk = [v, v, v, v]
        if self.done == 5 and 0.62 < self.pct < 0.655 and b > 0.3:
            wk = [v * 0.5, v * 0.5, v, v]
        race_over = self.done >= self.laps
        gap_a = max(0.5, 2.2 - self.done * 0.12)
        gap_b = max(0.4, 1.5 - self.done * 0.08)
        fr = Frame("TEST", "Test Ring", "Test Car", self.done, self.pct, v, th, b, st, 4, 7000,
                   self.cur, self.last, False, False, self.fuel, 4000.0, [85, 86, 84, 85], 8000.0, wk,
                   [27.0, 27.2, 26.8, 27.1], session="race", position=2, cars=16, race_laps=self.laps,
                   gap_ahead=gap_a, gap_behind=gap_b, race_over=race_over,
                   car_ahead={"name": "Max Verstappen", "position": 1, "car": "Red Bull RB21",
                              "distance_m": round(gap_a * 32), "gap_s": gap_a},
                   car_behind={"name": "Lando Norris", "position": 3, "car": "McLaren MCL39",
                               "distance_m": round(gap_b * 32), "gap_s": gap_b})
        return fr





CAPTURE_DEFAULT_S = 60
CAPTURE_MAX_S = 300
CAPTURE_AT_START = 0
_RE_KEYLIKE = re.compile(r"\b(?:sk-|AIza|gh[opsu]_)[A-Za-z0-9_\-]{6,}|(?i:\bbearer\s+)[A-Za-z0-9._\-]{12,}|"
                         r"(?i:api[_-]?key[\"']?\s*[:=]\s*[\"']?)[^\s\"',]{6,}")
CAPTURE_README = """SimCoach capture
================
Raw game data, recorded so SimCoach's readings can be checked against a real session.

meta.json         sim, track, car, SimCoach build, when and how long
raw/*.bin         the sim's shared-memory blocks, 4 times a second (index.jsonl: which block, and when)
udp_packets.bin   UDP sims (F1, EA WRC, DiRT Rally 2): every packet, as [double time][uint32 length][bytes]
frames.jsonl      what SimCoach read from them, 20 times a second
log.jsonl         what SimCoach logged and what the crew said, with times

Game data only: no settings, keys or anything else from your SimCoach config.
"""


def capture_dir():
    return os.path.join(REPORT_DIR, "Captures")


class Capture:
    """Records the active reader's raw memory blocks (4 a second) or its UDP packets, the frames decoded from them
    (20 a second) and the log, into one zip in SimCoach Reports\\Captures. Started by voice, a wheel button, the
    Log tab or --capture; it begins on the first frame from a sim and stops by itself."""
    RAW_HZ, FRAME_HZ = 4.0, 20.0
    RAW_LIMIT = 400 * 2 ** 20
    UDP_LIMIT = 64 * 2 ** 20

    def __init__(self, voice=None, log=print):
        self.voice, self.log = voice, log
        self.lock = threading.Lock()
        self.want = 0
        self.active = False
        self.stop_req = False
        self.saving = False
        self.last_path = None
        self.last_seen = -99.0
        self.reader = None
        self.q = None
        self.worker = None
        self._quiet_start = True
        self._atexit = False
        self.starting = False
        self.ended = None

    def arm(self, seconds=None):
        secs = int(max(10, min(CAPTURE_MAX_S, seconds or CAPTURE_DEFAULT_S)))
        with self.lock:
            if self.active or self.starting:
                return f"Already capturing, {self.left()} seconds to go."
            if self.saving:
                return "Still saving the last capture. Ask again in a moment."
            self.want, self.stop_req = secs, False
            self._quiet_start = time.monotonic() - self.last_seen < 2.0
        if self._quiet_start:
            return f"Capturing game data for {secs} seconds. Just drive normally."
        return f"Capture's armed: {secs} seconds, starting as soon as you're on track."

    def stop(self):
        with self.lock:
            if self.active or self.starting:
                self.stop_req = True
                return "Stopping the capture. Saving it now."
            if self.want:
                self.want = 0
                return "Capture cancelled."
        return "No capture running."

    def toggle(self, seconds=None):
        return self.stop() if (self.active or self.want) else self.arm(seconds)

    def left(self, now=None):
        if not self.active:
            return 0
        return max(0, int(round(self.end - (self._now if now is None else now))))

    def status(self):
        if self.active:
            return f"Capturing: {self.left()} s to go"
        if self.saving:
            return "Saving the capture..."
        if self.want:
            return f"Capture armed ({self.want} s): waiting for a sim"
        if self.last_path:
            return f"Last capture: {os.path.basename(self.last_path)}"
        return ""

    def sample(self, reader, f, now):
        """Called every loop with the active reader, before the coach sees the frame (so the frame is the reader's
        own output). Never blocks: anything the writer can't keep up with is counted and dropped."""
        if f is not None:
            self.last_seen = time.monotonic()
        if not self.active:
            if not self.want or f is None:
                return
            self._begin(reader, f, now)
        elif not self.worker.is_alive():
            self.finish("writer stopped")
            return
        self._now = now
        t = now - self.t0
        if now >= self.next_raw:
            self.next_raw = max(self.next_raw + 1.0 / self.RAW_HZ, now)
            if self.raw_bytes < self.RAW_LIMIT:
                blocks = {}
                for name, blk in reader.raw_blocks().items():
                    size = getattr(blk, "size", None) or len(blk)
                    data = bytes(blk[0:size])
                    blocks[name] = data
                    self.raw_bytes += len(data)
                if blocks:
                    self._put(("raw", t, blocks))
            self._drain_udp(reader)
        if f is not None and now >= self.next_frame:
            import dataclasses
            self.next_frame = max(self.next_frame + 1.0 / self.FRAME_HZ, now)
            self.frames += 1
            if self.frames == 1 or not self.meta.get("track"):
                self.meta.update(sim=f.game, track=f.track, car=f.car)
            self._put(("frame", t, dataclasses.asdict(f)))
        if self.stop_req or now >= self.end:
            self.finish("stopped early" if self.stop_req else "done")

    def _drain_udp(self, reader):
        take = getattr(reader, "cap_take", None)
        if take is None:
            return
        pk = take()
        if pk and self.udp_bytes < self.UDP_LIMIT:
            self.udp_bytes += sum(len(d) for _, d in pk)
            self._put(("udp", [(pt - self.m0, d) for pt, d in pk]))

    def _put(self, item):
        try:
            self.q.put_nowait(item)
        except queue.Full:
            self.dropped += 1

    def _begin(self, reader, f, now):
        global _LOG_TAP
        with self.lock:
            secs, self.want = self.want, 0
            self.starting, self.stop_req = True, False
        try:
            self.reader, self.t0, self.m0, self._now = reader, now, time.monotonic(), now
            self.end = now + secs
            self.next_raw = self.next_frame = now
            self.raw_bytes = self.udp_bytes = self.frames = self.dropped = 0
            state = {k: v for k, v in vars(reader).items() if isinstance(v, (bool, int, float, str)) and not k.startswith("__")}
            self.meta = {"app": "SimCoach", "build_md5": None, "reader": type(reader).__name__,
                         "reader_name": reader.name, "reader_state": state, "sim": f.game if f else None,
                         "track": f.track if f else None, "car": f.car if f else None,
                         "started": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": secs, "raw_hz": self.RAW_HZ,
                         "frame_hz": self.FRAME_HZ, "python": sys.version.split()[0], "platform": None,
                         "blocks": {n: (getattr(b, "size", None) or len(b)) for n, b in reader.raw_blocks().items()}}
            self.logs = []
            self.q, self.ended = queue.Queue(maxsize=400), threading.Event()
            m0, logs, llock = self.m0, self.logs, threading.Lock()

            def tap(msg, m0=m0, logs=logs, llock=llock):
                with llock:
                    if len(logs) < 20000:
                        logs.append({"t": round(time.monotonic() - m0, 3), "msg": _RE_KEYLIKE.sub("[key removed]", str(msg))})
            start = getattr(reader, "cap_start", None)
            if start is not None:
                start()
            _LOG_TAP = tap
            if not self._atexit:
                self._atexit = True
                atexit.register(lambda: self.finish("app closed", wait=True))
            self.worker = threading.Thread(target=self._write, args=(self.q, self.ended, self.meta, self.logs),
                                           daemon=False, name="capture-writer")
            self.worker.start()
            with self.lock:
                self.active = True
        finally:
            self.starting = False
        self.log(f"Capture started: {secs} s of {reader.name} data")
        if not self._quiet_start and self.voice is not None:
            self.voice.say(f"Capture running, {secs} seconds.", now, "info")

    def finish(self, reason="done", wait=False):
        """End the capture (if one is running) and let the writer save it. Never blocks unless wait=True."""
        global _LOG_TAP
        with self.lock:
            running = self.active
            if running:
                self.active, self.stop_req, self.saving = False, False, True
        if not running:
            worker = self.worker
            if wait and worker is not None and worker.is_alive():
                worker.join(15.0)
            return
        _LOG_TAP = None
        reader, self.reader = self.reader, None
        try:
            self._drain_udp(reader)
            stop = getattr(reader, "cap_stop", None)
            if stop is not None:
                stop()
        except Exception:
            pass
        self.meta.update(ended=reason, duration_s=round(self._now - self.t0, 2), frames=self.frames,
                         raw_bytes=self.raw_bytes, udp_bytes=self.udp_bytes, dropped=self.dropped,
                         raw_truncated=self.raw_bytes >= self.RAW_LIMIT)
        self.ended.set()
        if self.worker is None or not self.worker.is_alive():
            with self.lock:
                self.saving = False
        if wait and self.worker is not None:
            self.worker.join(15.0)

    def abort(self, why):
        self.log(f"Capture stopped: {why}")
        with self.lock:
            self.want = 0
        self.finish(f"error: {why}")

    def _write(self, q, ended, meta, logs):
        import hashlib
        import platform
        import zipfile
        stamp = time.strftime('%Y-%m-%d_%H%M%S')
        main = threading.main_thread()
        tmp, ok, path = None, False, None
        index, frames, udp, seq = [], [], bytearray(), 0
        try:
            try:
                with open(os.path.abspath(__file__), "rb") as fh:
                    meta["build_md5"] = hashlib.md5(fh.read()).hexdigest()
                meta["platform"] = platform.platform()
            except Exception:
                pass
            os.makedirs(capture_dir(), exist_ok=True)
            tmp = os.path.join(capture_dir(), f"{stamp}_capture.zip.part")
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as z:
                while True:
                    try:
                        item = q.get(timeout=0.25)
                    except queue.Empty:
                        if ended.is_set():
                            break
                        if not main.is_alive():
                            meta.setdefault("ended", "app closed")
                            break
                        continue
                    if item[0] == "raw":
                        for name, data in item[2].items():
                            fn = f"raw/{seq:05d}_{name}.bin"
                            z.writestr(fn, data)
                            index.append({"seq": seq, "t": round(item[1], 4), "name": name, "file": fn, "size": len(data)})
                        seq += 1
                    elif item[0] == "udp":
                        for pt, d in item[1]:
                            udp += struct.pack("<dI", pt, len(d)) + d
                    elif item[0] == "frame":
                        frames.append(json.dumps({"t": round(item[1], 4), "frame": item[2]}, default=str))
                z.writestr("index.jsonl", "\n".join(json.dumps(x) for x in index))
                z.writestr("frames.jsonl", "\n".join(frames))
                if udp:
                    z.writestr("udp_packets.bin", bytes(udp))
                z.writestr("log.jsonl", "\n".join(json.dumps(x) for x in list(logs)))
                z.writestr("meta.json", json.dumps(meta, indent=1, default=str))
                z.writestr("README.txt", CAPTURE_README)
            parts = [stamp] + [str(meta.get(k_) or "")[:40] for k_ in ("sim", "track")]
            stem = _RE_SAFE_REPORT.sub("_", "_".join(x for x in parts if x)).strip("_")
            path = os.path.join(capture_dir(), stem + ".zip")
            k = 2
            final = path
            while os.path.exists(final):
                final, k = path[:-4] + f"_{k}.zip", k + 1
            os.replace(tmp, final)
            ok, path = True, final
        except Exception as e:
            self.log(f"Capture couldn't be saved: {e}")
        finally:
            if not ok and tmp:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
            with self.lock:
                self.saving = False
                if ok:
                    self.last_path = path
        if ok:
            self.log(f"Capture saved: {path}")
            if self.voice is not None:
                self.voice.say("Capture saved. It's in your SimCoach Reports folder, under Captures.",
                               getattr(self, "_now", time.monotonic()), "info")


UNSUPPORTED_SIMS = (
    ("nascar25", "NASCAR 25", "NASCAR 25 doesn't share any telemetry, so I can't follow the car. Voice questions still work."),
    ("projectmotorracing", "Project Motor Racing",
     "Project Motor Racing's telemetry format isn't published, so I can't read it yet."),
    ("nascarheat5", "NASCAR Heat 5", "I can't read NASCAR Heat 5's telemetry, it only goes to SimHub's own plugin."),
    ("project_k", "KartKraft", "KartKraft isn't supported yet."),
    ("wrcg.exe", "WRC Generations", "WRC Generations isn't supported. EA SPORTS WRC is."),
    ("beamng.drive", "BeamNG.drive", "BeamNG isn't supported."),
)


def unsupported_sim():
    """(name, message) for a running game SimCoach can't read, else None."""
    for exe, name, msg in UNSUPPORTED_SIMS:
        if running(exe):
            return name, msg
    return None


def coach_loop(coach, readers, stop, test=False):
    cap = getattr(coach, "capture", None)
    active, clock = None, 0.0
    told = None
    err_msg, err_t = None, -99.0
    dt = 1.0 / LOOP_HZ
    next_tick = 0.0
    while not stop.is_set():
        if active is None:
            active = next((r for r in readers if _safe(r.connected)), None)
            if active is None:
                if test:
                    break
                other = _safe(unsupported_sim)
                if other:
                    coach.overlay.post(head=f"{other[0]}: no telemetry SimCoach can read")
                    if other[0] != told:
                        told = other[0]
                        coach.log(other[1])
                        coach.voice.say(other[1], time.monotonic(), "info")
                else:
                    told = None
                    coach.overlay.post(head="Waiting for a sim...")
                stop.wait(2)
                continue
            coach._active_reader = active
            coach.log(f"Connected to {active.name}")
            next_tick = time.monotonic()
        try:
            if not active.connected():
                coach.log("Sim closed")
                coach.clear_delta()
                coach.closed_after_finish = coach.race_finished
                if coach.race_finished and coach.history and not coach.pit_debrief_done:
                    coach.pit_debrief_done = True
                    coach.after_race_debrief(coach.last_frame, clock if test else time.monotonic())
                coach.end_session()
                if cap is not None:
                    cap.finish("sim closed")
                active = None
                continue
            f = active.read()
        except Exception as e:
            coach.log(f"Read error: {e}")
            active = None
            stop.wait(1)
            continue
        now = clock if test else time.monotonic()
        if cap is not None and (cap.want or cap.active):
            try:
                cap.sample(active, f, now)
            except Exception as e:
                cap.abort(f"{type(e).__name__}: {e}")
        if f is not None:
            try:
                coach.update(f, now)
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                if msg != err_msg or now - err_t > 10.0:
                    err_msg, err_t = msg, now
                    coach.log(f"Coach error: {msg}")
                    file_log(traceback.format_exc())
                if test:
                    raise
        if test:
            clock += dt
        else:
            next_tick += dt
            rem = next_tick - time.monotonic()
            if rem > 0.001:
                time.sleep(rem)
            elif rem < -dt:
                next_tick = time.monotonic()
    if cap is not None:
        cap.finish("coaching stopped", wait=test)


def _safe(fn):
    try:
        return fn()
    except Exception:
        return False


_INSTANCE = None


def _single_instance():
    """One SimCoach at a time (two copies fight over the telemetry ports). Windows named mutex."""
    global _INSTANCE
    if sys.platform != "win32" or ctypes is None:
        return True
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = wintypes.HANDLE
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        _INSTANCE = k32.CreateMutexW(None, False, "Local\\SimCoachSingleInstance")
        return ctypes.get_last_error() != 183
    except Exception:
        return True


def first_run_setup():
    """Run by the installer (uv has already installed the packages by the time this starts): pre-compile the
    heavy imports and download the offline speech model, so the first real launch opens straight away.
    Every step is optional: a failure here only means that step happens on first use instead."""
    cfg = load_config()
    steps = 0
    print("SimCoach setup: checking packages...", flush=True)
    for mod in ("numpy", "pygame", "sounddevice", "faster_whisper", "edge_tts", "openai", "psutil"):
        try:
            __import__(mod)
            print(f"  ok  {mod}", flush=True)
            steps += 1
        except Exception as e:
            print(f"  --  {mod}: {e}", flush=True)
    name = cfg.get("whisper_model") or "small.en"
    if name != "openai":
        print(f"Downloading the offline speech model ({name}), a few hundred MB the first time...", flush=True)
        try:
            from faster_whisper import download_model
            download_model(name)
            print("  ok  speech model", flush=True)
        except Exception as e:
            print(f"  --  speech model will download on first use ({e})", flush=True)
    if cfg.get("csp_weather_app", True):
        where = install_csp_weather_app(lambda m: print("  " + m, flush=True))
        print("  ok  AC weather link for CSP / Pure" if where else "  --  AC weather link: no Assetto Corsa with CSP found",
              flush=True)
    try:
        save_config(cfg)
        os.makedirs(REPORT_DIR, exist_ok=True)
        os.makedirs(REF_DIR, exist_ok=True)
    except Exception:
        pass
    print("SimCoach setup finished.", flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser(description=f"SimCoach {APP_VERSION} live voice coach")
    ap.add_argument("--version", action="version", version=f"SimCoach {APP_VERSION}")
    ap.add_argument("--bind", metavar="ACTION", nargs="?", const="ptt",
                    help="bind a wheel button: ptt, repeat, mute or tones (default ptt)")
    ap.add_argument("--no-overlay", action="store_true")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--no-mic", action="store_true")
    ap.add_argument("--test", action="store_true", help="offline run against simulated laps")
    ap.add_argument("--console", action="store_true", help="no main window, just the small overlay")
    ap.add_argument("--setup", action="store_true", help="installer step: warm up packages and the speech model")
    ap.add_argument("--capture", metavar="SECONDS", nargs="?", type=int, const=CAPTURE_DEFAULT_S, default=0,
                    help=f"record raw game data for checking (default {CAPTURE_DEFAULT_S} s) once a sim is running")
    a = ap.parse_args()
    global CAPTURE_AT_START
    CAPTURE_AT_START = max(0, a.capture or 0)
    if a.setup:
        sys.exit(first_run_setup())
    cfg = load_config()
    if not a.test:
        install_crash_logging()
        save_config(cfg)
        file_log(f"SimCoach {APP_VERSION} starting (Python {sys.version.split()[0]})")

    if a.bind:
        bind_button(cfg, a.bind)
        return

    if a.test:
        global REPORT_DIR
        REPORT_DIR = tempfile.mkdtemp()
        voice = Voice(cfg, enabled=False)
        voice.idle = lambda now, v=voice: now >= v.busy_until
        coach = Coach(cfg, voice, NullOverlay(), tempfile.mkdtemp())
        coach.crew = Crew(cfg, voice, NullOverlay(), coach=coach)
        if CAPTURE_AT_START:
            print("CAPTURE:", coach.capture.arm(CAPTURE_AT_START))
        coach_loop(coach, [SimReader()], threading.Event(), test=True)
        if CAPTURE_AT_START:
            print("CAPTURE SAVED:", coach.capture.last_path)
        conv = Conversation(cfg, coach, voice, NullOverlay())
        for q in ["what was my last lap", "repeat that", "how much fuel", "suggest a setup", "be quiet",
                  "should I reset my brake bias", "is that normal", "reset reference", "what was my last lap"]:
            print("DRIVER:", q, "->", conv.local(q))
        print("SUMMARY:", json.dumps(coach.summary())[:400])
        print("REPORT:", coach.end_session())
        return

    if not _single_instance():
        msg = "SimCoach is already running. Look for its window (or the tray/taskbar)."
        print(msg)
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo("SimCoach", msg)
            r.destroy()
        except Exception:
            pass
        return

    if not a.console:
        if sys.platform == "win32" and ctypes is not None:
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SimCoach.App")
            except Exception:
                pass
        App(cfg, voice_on=not a.no_voice, mic_on=not a.no_mic).run()
        return

    overlay = NullOverlay() if a.no_overlay else Overlay()
    voice = Voice(cfg, enabled=not a.no_voice, log=file_log)
    controls = Controls(cfg, log=file_log)
    coach = Coach(cfg, voice, overlay, REF_DIR, log=file_log)
    coach.crew = Crew(cfg, voice, overlay, log=file_log, coach=coach)
    conv = Conversation(cfg, coach, voice, overlay, log=file_log)
    controls.on("repeat", lambda: voice.say(voice.last_text or "Nothing to repeat yet.", time.monotonic(), "urgent"))
    def _console_mute():
        muted = cfg.get("talk_level", 1) != 0
        cfg["talk_level"] = 0 if muted else 1
        voice.say("Coach muted. Answers only." if muted else "Coach back on.", time.monotonic(), "urgent")
    def _console_tones():
        on = cfg.get("brake_callouts", "focus") != "off"
        cfg["brake_callouts"] = "off" if on else "focus"
        voice.say("Braking tones off." if on else "Braking tones on.", time.monotonic(), "urgent")
    controls.on("mute", _console_mute)
    controls.on("tones", _console_tones)

    def _console_capture():
        msg = coach.capture.toggle()
        file_log(msg)
        voice.say(msg, time.monotonic(), "urgent")
    controls.on("capture", _console_capture)
    controls.on("sheet", lambda: (coach.collaborate_race_setup(coach.last_frame, time.monotonic(), speak=False, use_openai=False, show=True)
                                  if not coach.last_setup_sheet and coach.last_frame is not None else overlay.post(setup_toggle=True)))
    if cfg.get("csp_weather_app", True):
        threading.Thread(target=install_csp_weather_app, args=(file_log,), daemon=True, name="csp-app").start()
    if CAPTURE_AT_START:
        print(coach.capture.arm(CAPTURE_AT_START))
    if not a.no_mic:
        Listener(cfg, voice, controls, conv.handle, log=file_log)
    stop = threading.Event()
    readers = available_readers(cfg, log=print)
    print(f"SimCoach running. Config: {CONFIG_PATH}")
    t = threading.Thread(target=coach_loop, args=(coach, readers, stop), daemon=True)
    t.start()
    try:
        if isinstance(overlay, Overlay):
            overlay.run()
        else:
            while t.is_alive():
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    stop.set()
    coach.end_session()


if __name__ == "__main__":
    main()

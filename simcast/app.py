"""SimCast's engine room: reads the sim (or the demo race), keeps the race tracker and the director going, and
holds what the window shows. Settings live in %APPDATA%\\SimCast\\config.json; the AI provider, keys and
driver name come from SimCoach's settings unless SimCast has its own."""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from collections import deque

from .audio import BroadcastAudio, SimAudio
from .demo import DemoRace
from .director import Director
from .race import RaceTracker
from . import ai as ai_mod

APP_NAME = "SimCast"
APP_VERSION = "1.0"
APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "SimCast")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOOP_HZ = 30
DEFAULTS = {
    "lead_name": "Ben", "analyst_name": "Kate", "pit_name": "Mia",
    "lead_voice": "en-GB-RyanNeural", "analyst_voice": "en-GB-SoniaNeural", "pit_voice": "en-AU-NatashaNeural",
    "openai_lead_voice": "ash", "openai_analyst_voice": "coral", "openai_pit_voice": "sage",
    "tts": "edge", "openai_tts_model": "gpt-4o-mini-tts", "speech_rate": 0,
    "volume": 0.9, "audio_out": "",
    "chatter": "normal", "focus": "balanced", "pit_reporter": True, "ai_colour": True,
    "driver_name": "", "ai_provider": "", "openai_api_key": "", "gemini_api_key": "", "deepseek_api_key": "",
    "demo_laps": 8, "captions": False, "captions_pos": None, "window": None,
}
CHOICES = {"tts": ("edge", "openai", "off"), "chatter": ("quiet", "normal", "chatty"),
           "focus": ("field", "balanced", "me")}
SECRET_KEYS = ("openai_api_key", "gemini_api_key", "deepseek_api_key")
ROLE_LABEL = {"lead": "lead", "analyst": "analyst", "pit": "pit lane"}


def load_config(path=None):
    path = path or CONFIG_PATH
    cfg = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict):
            cfg.update({k: v for k, v in d.items() if k in DEFAULTS})
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"Settings unreadable ({e}); using defaults.")
    return clean_config(cfg)


def clean_config(cfg):
    for k, opts in CHOICES.items():
        if cfg.get(k) not in opts:
            cfg[k] = DEFAULTS[k]
    try:
        cfg["volume"] = max(0.0, min(1.0, float(cfg.get("volume", 0.9))))
    except (TypeError, ValueError):
        cfg["volume"] = 0.9
    try:
        cfg["speech_rate"] = max(-30, min(30, int(cfg.get("speech_rate", 0))))
    except (TypeError, ValueError):
        cfg["speech_rate"] = 0
    try:
        cfg["demo_laps"] = max(2, min(30, int(cfg.get("demo_laps", 8))))
    except (TypeError, ValueError):
        cfg["demo_laps"] = 8
    for k in ("lead_name", "analyst_name", "pit_name", "driver_name"):
        cfg[k] = " ".join(str(cfg.get(k) or "").split())[:40]
    return cfg


def save_config(cfg, path=None):
    path = path or CONFIG_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({k: cfg.get(k) for k in DEFAULTS}, fh, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"Couldn't save settings: {e}")


class SimCast:
    def __init__(self, sc, cfg=None, audio=None, log=print, booth=True, save=True):
        self.sc = sc
        self.cfg = cfg or load_config()
        self.save_enabled = save
        self.log = log
        self._simcoach_cfg = {}
        self._simcoach_t = -1e9
        self.lines: deque = deque(maxlen=200)
        self.events_seen = 0
        self.tracker = RaceTracker(log=log)
        if audio is None:
            audio = BroadcastAudio(self.config, on_line=self._on_line, log=log, openai_client=self._openai_client)
        else:
            audio.on_line = self._on_line
        self.audio = audio
        self.booth = ai_mod.AIBooth(self.config, sc.ai_chat, sc._json_reply, label_fn=sc.ai_label, log=log) \
            if booth else None
        self.director = Director(self.tracker, self.audio, self.config, booth=self.booth, log=log)
        self.status = "Waiting for a sim..."
        self.source = None
        self.demo = None
        self.readers = None
        self.last_frame_t = None
        self.lock = threading.RLock()
        self.errors = deque(maxlen=5)

    # -------------------------------------------------------------- settings
    def config(self):
        """SimCast's settings, with the AI provider, keys and driver name from SimCoach unless set here."""
        now = time.monotonic()
        if now - self._simcoach_t > 30:
            self._simcoach_t = now
            try:
                self._simcoach_cfg = self.sc.load_config()
            except Exception:
                self._simcoach_cfg = {}
        out = dict(self._simcoach_cfg)
        for k, v in self.cfg.items():
            if v not in ("", None) or k not in out:
                out[k] = v
        if not out.get("ai_provider"):
            out["ai_provider"] = self._simcoach_cfg.get("ai_provider") or "openai"
        return out

    def update_settings(self, changes):
        """From the Settings window. Unknown keys are ignored; key fields are only replaced when something's typed."""
        with self.lock:
            for k, v in (changes or {}).items():
                if k not in DEFAULTS:
                    continue
                if k in SECRET_KEYS and not str(v or "").strip():
                    continue
                if isinstance(DEFAULTS[k], bool):
                    v = bool(v)
                self.cfg[k] = v.strip() if isinstance(v, str) else v
            self.cfg = clean_config(self.cfg)
            self._simcoach_t = -1e9
            if self.save_enabled:
                save_config(self.cfg)

    def _openai_client(self, cfg):
        key = self.sc.ai_key(cfg, "openai")
        return self.sc.openai_client(key)

    # -------------------------------------------------------------- what's said
    def _on_line(self, line, t):
        cfg = self.config()
        name = cfg.get(f"{line.who}_name") or line.who
        self.lines.append({"who": line.who, "name": name, "text": line.text, "energy": line.energy,
                           "t": time.time()})
        self.director.heard(line)
        self.log(f"{name.upper():>6} | {line.text}")

    # -------------------------------------------------------------- frames in
    def feed(self, frame, now):
        if frame is None:
            return
        self.last_frame_t = now
        with self.lock:
            try:
                ev = self.tracker.update(frame, now)
            except Exception as e:
                self._error("Race tracker", e)
                return
            if ev:
                self.events_seen += len(ev)
                self.director.add(ev, now)

    def tick(self, now):
        with self.lock:
            try:
                self.director.tick(now)
            except Exception as e:
                self._error("Director", e)

    def _error(self, where, e):
        msg = f"{where}: {type(e).__name__}: {e}"
        if not self.errors or self.errors[-1] != msg:
            self.errors.append(msg)
            self.log(msg)
            try:
                self.sc.file_log(traceback.format_exc())
            except Exception:
                pass

    # -------------------------------------------------------------- demo
    def start_demo(self, laps=None):
        with self.lock:
            cfg = self.config()
            self.demo = DemoRace(self.sc, laps=laps or cfg.get("demo_laps", 8), seed=int(time.time()) % 1000,
                                 player_name=cfg.get("driver_name") or "")
            self.tracker.reset()
            self.director.reset()
            self.audio.interrupt(time.monotonic())
            self.status = "Demo race"
            self.source = "Demo"

    def stop_demo(self):
        with self.lock:
            if self.demo is not None:
                self.demo = None
                self.audio.interrupt(time.monotonic())
                self.tracker.reset()
                self.director.reset()
                self.status = "Waiting for a sim..."
                self.source = None

    # -------------------------------------------------------------- live loop
    def run(self, stop):
        """Read the demo or the first sim that's running, LOOP_HZ times a second, until stop is set."""
        active = None
        next_check = 0.0
        dt = 1.0 / LOOP_HZ
        last = time.monotonic()
        while not stop.is_set():
            now = time.monotonic()
            step, last = now - last, now
            try:
                if self.demo is not None:
                    if active is not None:
                        active, self.readers = None, None
                    fr = self.demo.read(min(step, 0.25))
                    self.feed(fr, now)
                    if self.demo is not None and self.demo.finished and self.director.wrapped and \
                            not self.audio.speaking(now):
                        self.status = "Demo finished"
                else:
                    if active is None and now >= next_check:
                        next_check = now + 2.0
                        if self.readers is None:
                            self.readers = self.sc.available_readers(self.sc.load_config(), log=self.log)
                        active = next((r for r in self.readers if self._safe(r.connected)), None)
                        if active is not None:
                            self.log(f"Connected to {active.name}")
                            self.source = active.name
                            self.status = f"Live: {active.name}"
                            self.tracker.reset()
                            self.director.reset()
                    if active is not None:
                        if not self._safe(active.connected):
                            self.log(f"{active.name} closed")
                            active, self.source, self.status = None, None, "Waiting for a sim..."
                        else:
                            fr = active.read()
                            if fr is not None and not fr.field:
                                self.status = f"Live: {active.name} (no field data: see help)"
                            elif fr is not None:
                                self.status = f"Live: {active.name}"
                            self.feed(fr, now)
                self.tick(now)
            except Exception as e:
                self._error("Loop", e)
                active = None
                stop.wait(1.0)
            rem = dt - (time.monotonic() - now)
            if rem > 0:
                stop.wait(rem)

    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception:
            return False

    # -------------------------------------------------------------- what the window shows
    def state(self):
        with self.lock:
            return self._state()

    def _state(self):
        tr = self.tracker
        cfg = self.config()
        ld = tr.leader()
        lap = None
        if ld is not None and tr.session == "race":
            lap = min(ld.laps + 1, tr.race_laps) if tr.race_laps else ld.laps + 1
        standings = []
        for s in tr.standings():
            s = dict(s)
            s["call"] = self.director.writer.n(s["id"])
            standings.append(s)
        public = {k: v for k, v in cfg.items() if k in DEFAULTS and k not in SECRET_KEYS}
        public["keys"] = {k: bool(self.sc.ai_key(cfg, k.split("_")[0])) for k in SECRET_KEYS}
        return {
            "app": APP_NAME, "version": APP_VERSION, "status": self.status, "source": self.source,
            "session": tr.session, "track": tr.track, "lap": lap, "laps": tr.race_laps or None,
            "time_left": tr.time_left, "flag": tr.flag, "started": tr.started, "finished": tr.finished,
            "standings": standings, "lines": list(self.lines)[-40:], "on_air": self.director.on_air,
            "speaking": self.audio.speaking(time.monotonic()),
            "ai": self.booth.label() if self.booth else "", "ai_error": self.booth.last_error if self.booth else "",
            "demo": self.demo is not None, "settings": public, "errors": list(self.errors),
            "voice_note": getattr(self.audio, "engine_note", ""),
        }


def headless_run(sc, laps=6, seed=3, cfg=None, booth=None, max_t=3600.0, log=print, events=True):
    """A whole demo race on a simulated clock with silent audio: returns the SimCast (lines in .lines and
    .audio.spoken). Used by --test and the tests."""
    cfg = dict(DEFAULTS, **(cfg or {}))
    audio = SimAudio()
    cast = SimCast(sc, cfg, audio=audio, log=log, booth=False, save=False)
    cast._simcoach_t = 1e18                     # don't read the real SimCoach settings in a test
    if booth is not None:
        cast.booth = booth
        cast.director.booth = booth
        booth.clock = lambda: clock[0]
    demo = DemoRace(sc, laps=laps, seed=seed, player_name=cfg.get("driver_name", ""), events=events)
    dt = 1.0 / LOOP_HZ
    clock = [0.0]
    while clock[0] < max_t:
        t = clock[0]
        cast.feed(demo.read(dt), t)
        cast.tick(t)
        audio.tick(t)
        if demo.finished and cast.director.wrapped and not audio.speaking(t):
            break
        clock[0] += dt
    return cast

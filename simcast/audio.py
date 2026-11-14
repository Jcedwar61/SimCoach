"""The broadcast: turns Lines into speech in each commentator's own voice, one after another like a real booth,
with the next lines synthesised while the current one plays, and the ability to cut someone off when the race
won't wait (the lead jumping in over the analyst for an overtake).

Voices: Microsoft neural voices (edge-tts, free, the default), Kokoro (free, runs on this PC), Google (free) or
OpenAI's speech model (your key; it takes a direction for each line, "excited, voice rising"). Each commentator
has their own. Excitement comes from pace, pitch and volume; if a voice's service can't be reached, the line is
spoken by Kokoro, then Google, then Windows' own voice, so the booth never goes silent.
SimAudio is a silent stand-in with a simulated clock for tests and --test runs.
"""
from __future__ import annotations

import asyncio
import atexit
import hashlib
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .writer import ANALYST, LEAD, PIT

VOICES = [   # (label, voice id): Microsoft neural (free, online), Google (free, online), Kokoro (free, on this PC),
             # OpenAI (uses your OpenAI key; each line gets a spoken direction, so it's the most lifelike)
    ("Ryan (British) - Microsoft", "en-GB-RyanNeural"),
    ("Sonia (British) - Microsoft", "en-GB-SoniaNeural"),
    ("Thomas (British) - Microsoft", "en-GB-ThomasNeural"),
    ("Libby (British) - Microsoft", "en-GB-LibbyNeural"),
    ("Maisie (British) - Microsoft", "en-GB-MaisieNeural"),
    ("Andrew (American) - Microsoft", "en-US-AndrewNeural"),
    ("Brian (American) - Microsoft", "en-US-BrianNeural"),
    ("Guy (American) - Microsoft", "en-US-GuyNeural"),
    ("Christopher (American) - Microsoft", "en-US-ChristopherNeural"),
    ("Emma (American) - Microsoft", "en-US-EmmaNeural"),
    ("Aria (American) - Microsoft", "en-US-AriaNeural"),
    ("Jenny (American) - Microsoft", "en-US-JennyNeural"),
    ("William (Australian) - Microsoft", "en-AU-WilliamNeural"),
    ("Natasha (Australian) - Microsoft", "en-AU-NatashaNeural"),
    ("Connor (Irish) - Microsoft", "en-IE-ConnorNeural"),
    ("Emily (Irish) - Microsoft", "en-IE-EmilyNeural"),
    ("Mitchell (New Zealand) - Microsoft", "en-NZ-MitchellNeural"),
    ("George (British) - Kokoro, offline", "kokoro:bm_george"),
    ("Lewis (British) - Kokoro, offline", "kokoro:bm_lewis"),
    ("Daniel (British) - Kokoro, offline", "kokoro:bm_daniel"),
    ("Fable (British) - Kokoro, offline", "kokoro:bm_fable"),
    ("Emma (British) - Kokoro, offline", "kokoro:bf_emma"),
    ("Isabella (British) - Kokoro, offline", "kokoro:bf_isabella"),
    ("Heart (American) - Kokoro, offline", "kokoro:af_heart"),
    ("Bella (American) - Kokoro, offline", "kokoro:af_bella"),
    ("Michael (American) - Kokoro, offline", "kokoro:am_michael"),
    ("Adam (American) - Kokoro, offline", "kokoro:am_adam"),
    ("Fenrir (American) - Kokoro, offline", "kokoro:am_fenrir"),
    ("Puck (American) - Kokoro, offline", "kokoro:am_puck"),
    ("British - Google", "google:en-GB"),
    ("American - Google", "google:en-US"),
    ("Australian - Google", "google:en-AU"),
    ("Irish - Google", "google:en-IE"),
    ("Ash - OpenAI (your key)", "openai:ash"),
    ("Ballad - OpenAI (your key)", "openai:ballad"),
    ("Coral - OpenAI (your key)", "openai:coral"),
    ("Echo - OpenAI (your key)", "openai:echo"),
    ("Fable - OpenAI (your key)", "openai:fable"),
    ("Onyx - OpenAI (your key)", "openai:onyx"),
    ("Nova - OpenAI (your key)", "openai:nova"),
    ("Sage - OpenAI (your key)", "openai:sage"),
    ("Shimmer - OpenAI (your key)", "openai:shimmer"),
    ("Verse - OpenAI (your key)", "openai:verse"),
]
VOICE_LABEL = {v: n for n, v in VOICES}
DEFAULT_VOICE = {LEAD: "en-GB-RyanNeural", ANALYST: "en-GB-SoniaNeural", PIT: "en-AU-NatashaNeural"}
FALLBACK_KOKORO = {LEAD: "bm_george", ANALYST: "bf_emma", PIT: "bf_isabella"}
KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx"
KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
KOKORO_MIN = {"kokoro-v1.0.int8.onnx": 50_000_000, "voices-v1.0.bin": 20_000_000}
GOOGLE_TLD = {"en-GB": "co.uk", "en-US": "com", "en-AU": "com.au", "en-IE": "ie"}


_KOKORO_OK = []


def on_wine():
    """True when running under Wine or Proton (Linux, Steam Deck)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return hasattr(ctypes.windll.ntdll, "wine_get_version")
    except Exception:
        return False


def kokoro_usable():
    """Kokoro needs NumPy and ONNX Runtime. On Windows they just work; under some Wine versions NumPy aborts the
    whole process when it loads (Wine 9.0 lacks a maths function it uses), so there it's tried once in a separate
    process first, and Kokoro is left out if that fails."""
    if _KOKORO_OK:
        return _KOKORO_OK[0]
    ok = True
    if on_wine():
        import subprocess
        try:
            r = subprocess.run([sys.executable, "-c", "import numpy, onnxruntime, kokoro_onnx"], timeout=90,
                               capture_output=True)
            ok = r.returncode == 0
        except Exception:
            ok = False
    else:
        try:
            import importlib.util
            ok = importlib.util.find_spec("kokoro_onnx") is not None
        except Exception:
            ok = False
    _KOKORO_OK.append(ok)
    return ok


def wine_numpy_guard():
    """Under a Wine where NumPy can't load, make 'import numpy' a plain ImportError instead of a crash: pygame
    tries NumPy when it starts (and copes without it), and Kokoro is left out."""
    if on_wine() and not kokoro_usable():
        sys.modules.setdefault("numpy", None)


def engine_of(voice):
    """('edge' | 'kokoro' | 'google' | 'openai', id) for a voice id."""
    v = (voice or "").strip()
    for eng in ("kokoro", "google", "openai"):
        if v.lower().startswith(eng + ":"):
            return eng, v.split(":", 1)[1]
    return "edge", v or "en-GB-RyanNeural"


ROLE_RATE = {LEAD: 6, ANALYST: 2, PIT: 4}            # % faster than the voice's normal pace
ENERGY = [(0, 0, 0), (4, 2, 0), (9, 5, 5), (15, 9, 10)]   # (rate %, pitch Hz, volume %) on top, by energy 0-3
TONE = {
    LEAD: "a British TV motorsport play-by-play commentator, brisk and authoritative",
    ANALYST: "a former racing driver working as a TV analyst, conversational, insightful, warm",
    PIT: "a pit-lane reporter on a TV broadcast, quick and clear over the noise of the pit lane",
}
TONE_ENERGY = ["calm and measured", "engaged and lively", "excited, voice rising, fast",
               "absolutely thrilled, shouting over the crowd, at full pace"]
GAP_SAME, GAP_SWITCH = 0.12, 0.28                     # pause between lines: same speaker / a new speaker


def duration(text):
    """Seconds a line takes to say at broadcast pace."""
    return 0.35 + len(text.split()) / 2.9


class BaseAudio:
    def __init__(self, on_line=None):
        self.on_line = on_line or (lambda line, t: None)
        self.current_priority = 0
        self.last_end = -1e9

    def say(self, lines, priority, now):
        raise NotImplementedError

    def speaking(self, now) -> bool:
        raise NotImplementedError

    def interrupt(self, now):
        raise NotImplementedError

    def idle_for(self, now):
        return 0.0 if self.speaking(now) else max(0.0, now - self.last_end)


class SimAudio(BaseAudio):
    """No sound: each line 'plays' for duration(text) on the caller's clock. on_line fires when it starts."""

    def __init__(self, on_line=None):
        super().__init__(on_line)
        self.busy_until = -1e9
        self.pending = []                                # (start time, line, priority)
        self.spoken = []

    def say(self, lines, priority, now):
        t = max(now, self.busy_until)
        prev = None
        for ln in lines:
            if prev is not None:
                t += GAP_SWITCH if ln.who != prev else GAP_SAME
            self.pending.append((t, ln, priority))
            t += duration(ln.text)
            prev = ln.who
        self.busy_until = t
        self.current_priority = priority
        self.tick(now)

    def tick(self, now):
        while self.pending and self.pending[0][0] <= now:
            t, ln, pr = self.pending.pop(0)
            self.spoken.append((t, ln))
            self.on_line(ln, t)

    def speaking(self, now):
        self.tick(now)
        if now >= self.busy_until:
            if self.busy_until > self.last_end:
                self.last_end = self.busy_until
            self.current_priority = 0
            return False
        return True

    def interrupt(self, now):
        self.tick(now)
        self.pending.clear()
        self.busy_until = now
        self.last_end = now
        self.current_priority = 0


class BroadcastAudio(BaseAudio):
    """Real speech through pygame (the same player SimCoach uses)."""

    def __init__(self, cfg_fn, on_line=None, log=print, openai_client=None):
        super().__init__(on_line)
        self.cfg_fn, self.log = cfg_fn, log
        self.openai_client = openai_client
        self.q: "queue.Queue" = queue.Queue()
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="tts")
        self._tmp = tempfile.mkdtemp(prefix="simcast_")
        atexit.register(shutil.rmtree, self._tmp, True)
        self._cache: dict = {}
        self._gen = 0                                    # bumped by interrupt(): anything older is dropped
        self._playing = False
        self._queued = 0
        self._lock = threading.Lock()
        self._mixer = False
        self._mixer_dev = None
        self._sapi = None
        self.muted = False
        self.engine_note = ""
        self._kokoro = None
        self._kokoro_dl = False
        self._kokoro_retry = 0.0
        self._kokoro_run = threading.Lock()
        threading.Thread(target=self._run, daemon=True, name="broadcast").start()

    # -------------------------------------------------------------- public
    def say(self, lines, priority, now):
        with self._lock:
            gen = self._gen
            self._queued += len(lines)
            self.current_priority = max(self.current_priority, priority) if self._playing else priority
        for ln in lines:
            self.q.put((gen, ln, priority, self.pool.submit(self._synth, ln)))

    def speaking(self, now=None):
        with self._lock:
            busy = self._playing or self._queued > 0
        if not busy:
            self.current_priority = 0
        return busy

    def idle_for(self, now=None):
        return 0.0 if self.speaking() else max(0.0, time.monotonic() - self.last_end)

    def interrupt(self, now=None):
        with self._lock:
            self._gen += 1
            self._queued = 0
        try:
            import pygame
            if self._mixer and pygame.mixer.get_init():
                pygame.mixer.music.fadeout(220)
        except Exception:
            pass

    def list_outputs(self):
        """Playback devices (headset, speakers...), as the Settings window lists them."""
        try:
            import pygame
            import pygame._sdl2.audio as sdl2_audio
            temp = not pygame.mixer.get_init()
            if temp:
                pygame.mixer.init()
            names = list(sdl2_audio.get_audio_device_names(False))
            if temp:
                pygame.mixer.quit()
                self._mixer = False
            return names
        except Exception:
            return []

    def preview(self, who, text, energy=1):
        """Say one line now (the settings page's voice test)."""
        from .writer import Line
        self.say([Line(who, text, energy)], 50, time.monotonic())

    # -------------------------------------------------------------- synthesis
    def _voice(self, who, cfg):
        return cfg.get(f"{who}_voice") or DEFAULT_VOICE.get(who, DEFAULT_VOICE[LEAD])

    def _synth(self, ln):
        """A sound file for one line, or None. The chosen voice first; if its service can't be reached (no
        internet, no key), Kokoro on this PC, then Google; the caller falls back to Windows' own voice."""
        cfg = self.cfg_fn()
        if cfg.get("tts") == "off":
            return None
        engine, vid = engine_of(self._voice(ln.who, cfg))
        tries = [(engine, vid)]
        if engine != "kokoro":
            tries.append(("kokoro", FALLBACK_KOKORO.get(ln.who, "bm_george")))
        if engine != "google":
            tries.append(("google", "en-GB"))
        if not kokoro_usable():
            tries = [t for t in tries if t[0] != "kokoro"] or [("google", "en-GB")]
        for k, (eng, v) in enumerate(tries):
            key = hashlib.sha1(f"{eng}|{v}|{ln.energy}|{ln.who}|{cfg.get('speech_rate', 0)}|{ln.text}".encode()).hexdigest()[:20]
            path = os.path.join(self._tmp, key + (".wav" if eng == "kokoro" else ".mp3"))
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path
            try:
                getattr(self, "_synth_" + eng)(ln, v, cfg, path)
                if os.path.getsize(path) == 0:
                    raise RuntimeError("the voice service sent no audio")
                if k:
                    self.engine_note = f"{VOICE_LABEL.get(self._voice(ln.who, cfg), engine)} unavailable: using {eng}"
                return path
            except Exception as e:
                try:
                    os.remove(path)                              # never cache a failed (empty) file
                except OSError:
                    pass
                if k == 0:
                    self.engine_note = f"{engine} voice failed: {type(e).__name__}: {e}"[:200]
                    self.log(f"Voice: {self.engine_note}")
        return None

    _tls = threading.local()

    def _synth_edge(self, ln, voice, cfg, path):
        import edge_tts
        r, p, v = ENERGY[max(0, min(3, ln.energy))]
        rate = ROLE_RATE.get(ln.who, 0) + r + int(cfg.get("speech_rate", 0))
        loop = getattr(self._tls, "loop", None)
        if loop is None or loop.is_closed():
            loop = self._tls.loop = asyncio.new_event_loop()
        comm = edge_tts.Communicate(ln.text, voice, rate=f"{rate:+d}%", pitch=f"{p:+d}Hz", volume=f"{v:+d}%")
        loop.run_until_complete(comm.save(path))

    def _synth_openai(self, ln, voice, cfg, path):
        if self.openai_client is None:
            raise RuntimeError("no OpenAI client")
        from .providers import tts_model
        client = self.openai_client(cfg)
        instructions = (f"Voice: {TONE.get(ln.who, TONE[LEAD])}. Delivery right now: "
                        f"{TONE_ENERGY[max(0, min(3, ln.energy))]}. Natural live broadcast, not reading a script.")
        speed = max(0.8, min(1.3, 1.0 + (ROLE_RATE.get(ln.who, 0) + int(cfg.get("speech_rate", 0))) / 100.0))
        with client.audio.speech.with_streaming_response.create(
                model=tts_model(cfg), voice=voice, input=ln.text, instructions=instructions,
                response_format="mp3", speed=speed) as resp:
            resp.stream_to_file(path)

    def _synth_google(self, ln, voice, cfg, path):
        from gtts import gTTS
        gTTS(text=ln.text, lang="en", tld=GOOGLE_TLD.get(voice, "co.uk")).save(path)

    # Kokoro: a neural voice that runs on this PC (no internet once its model is downloaded, ~115 MB, first use)
    def _kokoro_paths(self):
        from .app import APP_DIR
        kdir = os.path.join(APP_DIR, "kokoro")
        return kdir, os.path.join(kdir, "kokoro-v1.0.int8.onnx"), os.path.join(kdir, "voices-v1.0.bin")

    def _kokoro_download(self):
        import shutil
        import urllib.request
        try:
            kdir, mpath, vpath = self._kokoro_paths()
            os.makedirs(kdir, exist_ok=True)
            self.log("Downloading the Kokoro voice model (first use only, about 115 MB)...")
            for url, dst in ((KOKORO_MODEL_URL, mpath), (KOKORO_VOICES_URL, vpath)):
                if os.path.exists(dst):
                    continue
                tmp = dst + ".part"
                req = urllib.request.Request(url, headers={"User-Agent": "SimCast/1.0"})
                with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
                    shutil.copyfileobj(resp, out)
                if os.path.getsize(tmp) < KOKORO_MIN[os.path.basename(dst)]:
                    os.remove(tmp)
                    raise RuntimeError(f"the download of {os.path.basename(dst)} was incomplete")
                os.replace(tmp, dst)
            self.log("Kokoro voices ready.")
        except Exception as e:
            self._kokoro_retry = time.monotonic() + 300
            self.log(f"Kokoro download failed ({e}); will try again in 5 minutes.")
        finally:
            self._kokoro_dl = False

    def _kokoro_model(self):
        if self._kokoro is not None:
            return self._kokoro
        from kokoro_onnx import Kokoro
        if time.monotonic() < self._kokoro_retry:
            raise RuntimeError("Kokoro isn't available right now")
        _d, mpath, vpath = self._kokoro_paths()
        if not (os.path.exists(mpath) and os.path.exists(vpath)):
            with self._lock:
                if not self._kokoro_dl:
                    self._kokoro_dl = True
                    threading.Thread(target=self._kokoro_download, daemon=True, name="kokoro-download").start()
            raise RuntimeError("the Kokoro voices are still downloading")
        with self._lock:
            if self._kokoro is None:
                self._kokoro = Kokoro(mpath, vpath)
        return self._kokoro

    def _synth_kokoro(self, ln, voice, cfg, path):
        import wave
        import numpy as np
        r = ENERGY[max(0, min(3, ln.energy))][0] + ROLE_RATE.get(ln.who, 0) + int(cfg.get("speech_rate", 0))
        speed = max(0.6, min(1.6, 1.0 + r / 100.0))
        with self._kokoro_run:                                   # one at a time: it's CPU-heavy
            samples, sr = self._kokoro_model().create(ln.text, voice=voice, speed=speed,
                                                      lang="en-gb" if voice.startswith("b") else "en-us")
        pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(sr))
            wf.writeframes(pcm)

    # -------------------------------------------------------------- playback
    def _init_mixer(self):
        dev = self.cfg_fn().get("audio_out") or None
        if self._mixer and dev == self._mixer_dev:
            return True
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.quit()
            try:
                pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=1024, devicename=dev)
            except Exception as e:
                if dev:
                    self.log(f"Audio device '{dev}' unavailable ({e}); using the default.")
                pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=1024)
            self._mixer, self._mixer_dev = True, dev
        except Exception as e:
            self._mixer = False
            self.log(f"No audio output: {e}")
        return self._mixer

    def _sapi_say(self, text):
        if sys.platform != "win32":
            return False
        try:
            if self._sapi is None:
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize()
                self._sapi = win32com.client.Dispatch("SAPI.SpVoice")
            self._sapi.Volume = int(float(self.cfg_fn().get("volume", 0.9)) * 100)
            self._sapi.Speak(text)
            return True
        except Exception:
            return False

    def _run(self):
        prev_who = None
        while True:
            gen, ln, prio, fut = self.q.get()
            try:
                path = fut.result(timeout=15)
            except Exception:
                path = None
            with self._lock:
                stale = gen != self._gen
                if not stale:
                    self._queued = max(0, self._queued - 1)
                    self._playing = True
                    self.current_priority = prio
            if stale:
                continue
            try:
                gap = GAP_SWITCH if (prev_who and ln.who != prev_who) else GAP_SAME
                if time.monotonic() - self.last_end < gap:
                    time.sleep(gap)
                self.on_line(ln, time.monotonic())
                prev_who = ln.who
                if self.muted or self.cfg_fn().get("tts") == "off":
                    self._wait(duration(ln.text), gen)
                elif path and self._init_mixer():
                    import pygame
                    pygame.mixer.music.load(path)
                    pygame.mixer.music.set_volume(float(self.cfg_fn().get("volume", 0.9)))
                    pygame.mixer.music.play()
                    t0 = time.monotonic()
                    while pygame.mixer.music.get_busy() and time.monotonic() - t0 < 30:
                        if gen != self._gen:
                            break
                        time.sleep(0.03)
                elif not self._sapi_say(ln.text):
                    self._wait(duration(ln.text), gen)
            except Exception as e:
                self.log(f"Playback: {e}")
            finally:
                with self._lock:
                    self._playing = False
                self.last_end = time.monotonic()

    def _wait(self, secs, gen):
        end = time.monotonic() + secs
        while time.monotonic() < end and gen == self._gen:
            time.sleep(0.05)

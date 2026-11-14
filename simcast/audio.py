"""The broadcast: turns Lines into speech in each commentator's own voice, one after another like a real booth,
with the next lines synthesised while the current one plays, and the ability to cut someone off when the race
won't wait (the lead jumping in over the analyst for an overtake).

Voices: Microsoft neural voices through edge-tts (free, default), or OpenAI's speech model, which takes a
direction for each line ("excited, voice rising"). Excitement on edge voices comes from pace, pitch and volume.
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

EDGE_VOICES = ["en-GB-RyanNeural", "en-GB-ThomasNeural", "en-GB-SoniaNeural", "en-GB-LibbyNeural",
               "en-GB-MaisieNeural", "en-US-AndrewNeural", "en-US-BrianNeural", "en-US-GuyNeural",
               "en-US-EmmaNeural", "en-US-AriaNeural", "en-US-JennyNeural", "en-AU-WilliamNeural",
               "en-AU-NatashaNeural", "en-IE-ConnorNeural", "en-IE-EmilyNeural", "en-NZ-MitchellNeural"]
OPENAI_VOICES = ["ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse"]
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

    def preview(self, who, text, energy=1):
        """Say one line now (the settings page's voice test)."""
        from .writer import Line
        self.say([Line(who, text, energy)], 50, time.monotonic())

    # -------------------------------------------------------------- synthesis
    def _voice(self, who, cfg):
        if cfg.get("tts") == "openai":
            return cfg.get(f"openai_{who}_voice") or {LEAD: "ash", ANALYST: "coral", PIT: "sage"}[who]
        return cfg.get(f"{who}_voice") or {LEAD: "en-GB-RyanNeural", ANALYST: "en-GB-SoniaNeural",
                                           PIT: "en-AU-NatashaNeural"}[who]

    def _synth(self, ln):
        cfg = self.cfg_fn()
        engine = cfg.get("tts", "edge")
        if engine == "off":
            return None
        voice = self._voice(ln.who, cfg)
        key = hashlib.sha1(f"{engine}|{voice}|{ln.energy}|{ln.who}|{ln.text}".encode()).hexdigest()[:20]
        path = os.path.join(self._tmp, key + ".mp3")
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        try:
            if engine == "openai" and self.openai_client is not None:
                self._synth_openai(ln, voice, cfg, path)
            else:
                self._synth_edge(ln, voice, path)
            if os.path.getsize(path) == 0:
                raise RuntimeError("the voice service sent no audio")
            return path
        except Exception as e:
            try:
                os.remove(path)                          # never cache a failed (empty) file
            except OSError:
                pass
            self.engine_note = f"{engine} voice failed: {type(e).__name__}: {e}"[:200]
            self.log(f"Voice: {self.engine_note}")
            if engine == "openai":
                try:
                    self._synth_edge(ln, self.cfg_fn().get(f"{ln.who}_voice") or "en-GB-RyanNeural", path)
                    if os.path.getsize(path) > 0:
                        return path
                except Exception:
                    pass
            return None

    _tls = threading.local()

    def _synth_edge(self, ln, voice, path):
        import edge_tts
        r, p, v = ENERGY[max(0, min(3, ln.energy))]
        rate = ROLE_RATE.get(ln.who, 0) + r + int(self.cfg_fn().get("speech_rate", 0))
        loop = getattr(self._tls, "loop", None)
        if loop is None or loop.is_closed():
            loop = self._tls.loop = asyncio.new_event_loop()
        comm = edge_tts.Communicate(ln.text, voice, rate=f"{rate:+d}%", pitch=f"{p:+d}Hz", volume=f"{v:+d}%")
        loop.run_until_complete(comm.save(path))

    def _synth_openai(self, ln, voice, cfg, path):
        client = self.openai_client(cfg)
        instructions = (f"Voice: {TONE.get(ln.who, TONE[LEAD])}. Delivery right now: "
                        f"{TONE_ENERGY[max(0, min(3, ln.energy))]}. British English. Natural live broadcast, "
                        f"not reading a script.")
        with client.audio.speech.with_streaming_response.create(
                model=cfg.get("openai_tts_model") or "gpt-4o-mini-tts", voice=voice, input=ln.text,
                instructions=instructions, response_format="mp3") as resp:
            resp.stream_to_file(path)

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

"""Push-to-talk pipeline end to end, with no real microphone.

A clip (tools/tests/data/ptt.npy, 48 kHz, light hiss) stands in for the mic: sounddevice is replaced by a fake
stream that feeds the clip in 1024-frame blocks for as long as it is open. That exercises the real Listener:
press -> pre-roll + blocks -> prep_speech -> transcribe -> tidy_speech -> on_text.
Needs numpy; the accuracy check also needs faster-whisper's small.en (about 15 s), else it is skipped.
"""
import os
import sys
import threading
import time
import types

from _common import check, done, load

sc = load()
try:
    import numpy as np
except Exception as e:
    print(f"skipped (needs numpy): {e}")
    done()

CLIP = np.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ptt.npy"))
EXPECT = "radio check. box this lap, fuel map to four please."
KEY = {"box", "lap", "fuel", "map", "four", "please", "radio", "check"}


class FakeStream:
    """Feeds the clip like a live mic: at the stream's own rate, in real time, for as long as it is open."""

    def __init__(self, **kw):
        self.rate = kw.get("samplerate", 48000)
        n = int(len(CLIP) * self.rate / 48000)
        self.clip = np.interp(np.arange(n) * (48000 / self.rate), np.arange(len(CLIP)), CLIP).astype(np.float32)
        self.cb, self.active, self.pos = kw["callback"], False, 0

    def start(self):
        self.active = True
        threading.Thread(target=self._feed, daemon=True).start()

    def stop(self):
        self.active = False

    def close(self):
        pass

    def _feed(self):
        while self.active:
            block = self.clip[self.pos:self.pos + 1024]
            if not len(block):
                block = np.zeros(1024, np.float32)
            self.pos += 1024
            self.cb(block.reshape(-1, 1), len(block), None, None)
            time.sleep(1024.0 / self.rate)


fake = types.SimpleNamespace(
    InputStream=FakeStream, WasapiSettings=lambda **k: k,
    query_devices=lambda i=None: {"name": "Fake mic", "default_samplerate": 48000.0,
                                  "max_input_channels": 1, "hostapi": 0},
    query_hostapis=lambda: [{"name": "Windows WASAPI"}])
sys.modules["sounddevice"] = fake


class Stub:
    """Stands in for Whisper: instant, and records what it was given."""

    def __init__(self):
        self.got = []

    def transcribe(self, audio, **kw):
        self.got.append((np.asarray(audio), kw))
        return iter([types.SimpleNamespace(text=EXPECT)]), None


def press(listener, seconds=1.0):
    """Hold the talk button, then wait for the clip to be recorded and handed on."""
    listener.gui_ptt.set()
    time.sleep(seconds)
    listener.gui_ptt.clear()
    for _ in range(200):
        if listener._chunks is not None:
            break
        time.sleep(0.02)


def make(stub):
    cfg = sc.load_config()
    cfg["mic"], cfg["mic_api"], cfg["whisper_model"] = "Fake mic", "wasapi", "small.en"
    heard, events = [], []
    listener = sc.Listener(cfg, types.SimpleNamespace(hold=threading.Event()), None, heard.append,
                           log=lambda m: None, events=lambda **kw: events.append(kw))
    listener._model, listener._model_name = stub, "small.en"
    for _ in range(150):
        if listener.state == "ready":
            break
        time.sleep(0.02)
    return listener, heard, events


stub = Stub()
listener, heard, events = make(stub)
check(listener.state == "ready", "listener is ready before the press")
press(listener, 2.0)
heard.clear()

press(listener, 0.9)
press(listener, 0.9)
press(listener, 1.2)
time.sleep(0.3)
press_ev = next((e for e in events if e.get("rc_ptt") is True), {})
release_ev = next((e for e in events if e.get("rc_ptt") is False), {})

check(press_ev.get("rc_api") == "wasapi", "the host API that opened the mic is reported to the radio check")
check(press_ev.get("rc_preroll", 0) > 0, f"pre-roll before the press is kept ({press_ev.get('rc_preroll')} blocks)")
check(release_ev.get("rc_clip_s", 9) > 0.8, "the clip spans the whole press, not just its tail")
check(any("rc_mic" in e for e in events), "the mic level was reported")
check(len(heard) == 1, f"exactly one message per press: {heard!r}")

audio, kw = stub.got[-1]
check(24000 * 0.9 < len(audio) < 16000 * 6, f"speech is resampled to 16 kHz and padded ({len(audio) / 16000:.1f} s)")
check(abs(float(np.abs(audio).max()) - 1.0) < 0.15, "the clip is normalised to full scale")
check(kw.get("hotwords") == sc.STT_HOTWORDS, "radio bias words are passed to the recogniser")
check(kw.get("without_timestamps") is True, "timestamps are off (faster)")
check("radio check" in heard[0].lower(), f"the words reach the coach: {heard[0]!r}")

listener.stop.set()
time.sleep(0.2)
check(not listener._stream.active if listener._stream else True, "the listener closes the microphone on stop")

try:
    from faster_whisper import WhisperModel
except Exception as e:
    print(f"(accuracy check skipped: {e})")
    done()
stub2 = WhisperModel("small.en", device="cpu", compute_type="int8")
listener, heard, events = make(Stub())
listener._model = stub2
press(listener, 6.2)
for _ in range(300):
    if heard:
        break
    time.sleep(0.1)
text = (heard or [""])[0].lower()
check(len(set(text.replace(",", "").replace(".", "").split()) & KEY) >= 6,
      f"the shipped pipeline transcribes the clip with the real model: {text!r}")
listener.stop.set()
done()

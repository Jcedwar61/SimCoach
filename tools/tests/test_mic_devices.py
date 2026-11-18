"""Microphone choice: the host API order, one list entry per mic, and falling back to the Windows default
when the chosen mic has gone (an unplugged headset must never kill push-to-talk), without an exclusive
WASAPI takeover."""
import sys
import types

from _common import check, done, load

sc = load()

# fake PortAudio table: MME first (its indexes are lowest), then DirectSound, then WASAPI
HOSTS = [{"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}]
DEVICES = [
    {"name": "Microphone (Pimax)", "max_input_channels": 1, "hostapi": 0},
    {"name": "Headset Microphone (Astro A20 V", "max_input_channels": 1, "hostapi": 0},
    {"name": "Primary Sound Capture Driver", "max_input_channels": 2, "hostapi": 1},
    {"name": "Headset Microphone (Astro A20 Voice)", "max_input_channels": 2, "hostapi": 2},
    {"name": "Speakers (Realtek)", "max_input_channels": 0, "hostapi": 2},
]
opened = []


class FakeStream:
    def __init__(self, **kw):
        opened.append(kw)

    def start(self):
        pass


fake = types.SimpleNamespace(query_hostapis=lambda: HOSTS,
                             query_devices=lambda i=None: DEVICES if i is None else DEVICES[i],
                             InputStream=FakeStream,
                             WasapiSettings=lambda **kw: ("shared", kw.get("exclusive")))
sys.modules["sounddevice"] = fake

check((sc._api_kind("Windows WASAPI"), sc._api_kind("Windows DirectSound"), sc._api_kind("MME")) ==
      ("wasapi", "directsound", "mme"), "host API names are recognised")
check(sc._api_kind("Windows WDM-KS") == "wdm" and sc._api_kind("ASIO") is None,
      "WDM-KS is a known fallback and ASIO is ignored")
listed = sc.list_input_devices({"mic_api": "auto"})
check(listed == ["Headset Microphone (Astro A20 Voice)", "Primary Sound Capture Driver",
                 "Microphone (Pimax)", "Headset Microphone (Astro A20 V"],
      f"every mic is listed once, best host API first: {listed}")
check(sc.list_input_devices({"mic_api": "wasapi"}) == ["Headset Microphone (Astro A20 Voice)"],
      "a pinned host API lists only its own mics")

cands = sc._input_candidates({"mic_api": "auto"}, "Headset Microphone (Astro A20 Voice)")
check(cands[0] == (3, "wasapi"), f"the chosen mic is used on WASAPI first: {cands[:1]}")
check((1, "mme") in cands or (3, "wasapi") in cands, "the mic keeps a fallback host API")
check(sc._input_candidates({"mic_api": "auto"}, "Nonexistent Mic")[0] == (None, "wasapi"),
      "a mic that has gone falls back to the Windows default")

opened.clear()
_platform = sys.platform
sys.platform = "win32"  # WASAPI settings only apply on Windows
try:
    sc.open_input({"mic_api": "auto"}, "Headset Microphone (Astro A20 Voice)", None)
finally:
    sys.platform = _platform
check(opened and opened[0]["device"] == 3, "open_input opens the chosen device")
check(opened[0]["extra_settings"] == ("shared", False), "WASAPI is opened in shared mode, not exclusive")
check(opened[0]["channels"] == 1 and opened[0]["dtype"] == "float32", "the mic is opened mono, float32")

opened.clear()
sc.open_input({"mic_api": "auto"}, "", None)
check(opened and "device" not in opened[0], "no mic chosen opens the Windows default")
check(sc._live_mic("Headset Microphone (Astro A20 V") == "Headset Microphone (Astro A20 Voice)",
      "a name cut at 31 characters matches the real device again")
done()

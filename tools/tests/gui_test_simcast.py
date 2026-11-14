"""SimCast's window, for real (needs a display: tools/run_tests.sh --gui runs it under xvfb-run): a demo race
fills the timing tower and the booth, Settings opens and saves, the captions window follows the booth, and the
off-air card comes back when the demo stops. SIMCAST_SHOTS=folder saves screenshots."""
import os
import sys
import time

import tempfile

from _common import REPO, check, done

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="simcast-gui-test-")
sys.path.insert(0, REPO)
from simcast.app import DEFAULTS, SimCast   # noqa: E402
from simcast.gui import SimCastWindow       # noqa: E402

SHOTS = os.environ.get("SIMCAST_SHOTS")
cfg = dict(DEFAULTS, tts="off", driver_name="Sam Carter", game_setup=False)
cast = SimCast(cfg, log=lambda m: None, booth=False, save=False)
win = SimCastWindow(cast)
root = win.root


def shot(name):
    if not SHOTS:
        return
    try:
        from PIL import ImageGrab
        root.update()
        x, y, w, h = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
        os.makedirs(SHOTS, exist_ok=True)
        ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=os.environ.get("DISPLAY")).save(os.path.join(SHOTS, name))
    except Exception as e:
        print(f"(screenshot failed: {e})")


def pump(secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        root.update()
        time.sleep(0.02)


win.loop.start()
root.after(50, win.poll)
pump(1.5)
check(win.hero.winfo_ismapped() and not win.body.winfo_ismapped(), "off air: the waiting card shows")
shot("simcast-offair.png")

win.toggle_demo()
pump(40)
rows = win.tree.get_children()
check(len(rows) == 12, f"demo: the timing tower lists the field ({len(rows)})")
check(win.body.winfo_ismapped() and not win.hero.winfo_ismapped(), "demo: tower and booth replace the card")
booth = win.text.get("1.0", "end")
check("BEN" in booth and ("away" in booth or "Lights out" in booth or "green flag" in booth.lower()),
      "demo: the booth's lines appear, with who said them")
me = [r for r in rows if "me" in win.tree.item(r, "tags")]
check(len(me) == 1 and "Carter" in win.tree.item(me[0], "values")[1], "demo: your car is highlighted")
check("Ridgeway Park" in win.session.cget("text") and "Lap" in win.session.cget("text"), "demo: track and lap")
shot("simcast-race.png")

win.open_settings()
pump(0.8)
sw = win.settings_win
check(sw is not None and sw.win.winfo_ismapped(), "settings: opens")
sw.v["chatter"].set("chatty")
sw.v["driver_name"].set("Sam C")
sw.voice_boxes["analyst"].set("Emma (British) - Kokoro, offline")
sw.model_boxes["openai"].set(sw.model_boxes["openai"].cget("values")[1])
if SHOTS:
    try:
        from PIL import ImageGrab
        sw.win.update()
        x, y = sw.win.winfo_rootx(), sw.win.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + sw.win.winfo_width(), y + sw.win.winfo_height()),
                       xdisplay=os.environ.get("DISPLAY")).save(os.path.join(SHOTS, "simcast-settings.png"))
    except Exception as e:
        print(f"(screenshot failed: {e})")
sw.save()
pump(0.3)
check(cast.cfg["chatter"] == "chatty" and cast.cfg["driver_name"] == "Sam C" and
      cast.cfg["analyst_voice"] == "kokoro:bf_emma", "settings: saved (Kokoro voice for the analyst)")
check(cast.cfg["openai_model"] not in ("", "auto") and cast.cfg["gemini_model"] == "auto",
      f"settings: a model picked by hand, the others automatic ({cast.cfg['openai_model']})")
check(cast.cfg["tts"] == "off", "settings: speech stays off (text only) when untouched")
win.open_settings()
sw2 = win.settings_win
labels = sw2.voice_boxes["lead"].cget("values")
check(any("Kokoro" in x for x in labels) and any("Google" in x for x in labels) and any("OpenAI" in x for x in labels)
      and any("Microsoft" in x for x in labels), "settings: Microsoft, Kokoro, Google and OpenAI voices offered")
check(sw2.model_boxes["openai"].cget("values")[0].startswith("Automatic (best: "), "settings: model on Automatic")
for i in range(5):
    sw2.nb.select(i)
    pump(0.2)
    if i in (1, 2, 4):
        if SHOTS:
            try:
                from PIL import ImageGrab
                sw2.win.update()
                x, y = sw2.win.winfo_rootx(), sw2.win.winfo_rooty()
                ImageGrab.grab(bbox=(x, y, x + sw2.win.winfo_width(), y + sw2.win.winfo_height()),
                               xdisplay=os.environ.get("DISPLAY")).save(os.path.join(SHOTS, f"simcast-settings-{i}.png"))
            except Exception as e:
                print(f"(screenshot failed: {e})")
sw2.win.destroy()

win.open_guide()
pump(0.6)
g = win.guide_win
check(g is not None and g.win.winfo_ismapped() and "Welcome to SimCast" in g.text.get("1.0", "end"), "guide: opens on Getting started")
g.show(len(g.topics) - 1)
lic = g.text.get("1.0", "end")
check("MIT License" in lic and "The Go Authors" in lic and "kokoro-onnx" in lic, "guide: licences and notices shown")
g.show(2)
if SHOTS:
    try:
        from PIL import ImageGrab
        g.win.update()
        x, y = g.win.winfo_rootx(), g.win.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + g.win.winfo_width(), y + g.win.winfo_height()),
                       xdisplay=os.environ.get("DISPLAY")).save(os.path.join(SHOTS, "simcast-guide.png"))
    except Exception as e:
        print(f"(screenshot failed: {e})")
g.win.destroy()

win.toggle_captions(True)
pump(12)
cap = win.captions
check(cap is not None and cap.win.winfo_ismapped() and cap.text.cget("text"), "captions window shows the booth's line")
win.toggle_captions(False)
check(win.captions is None, "captions window closes")

win.toggle_air()
check(not cast.director.on_air, "off air button")
win.toggle_air()
win.toggle_demo()
pump(1.5)
check(win.hero.winfo_ismapped(), "demo stopped: the waiting card is back")
win.close()
check(not cast.errors, f"no errors ({list(cast.errors)})")
done()

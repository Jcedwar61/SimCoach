"""SimCast's window, for real (needs a display: tools/run_tests.sh --gui runs it under xvfb-run): a demo race
fills the timing tower and the booth, Settings opens and saves, the captions window follows the booth, and the
off-air card comes back when the demo stops. SIMCAST_SHOTS=folder saves screenshots."""
import os
import sys
import time

from _common import REPO, check, done, load

sc = load()
sys.path.insert(0, REPO)
from simcast.app import DEFAULTS, SimCast   # noqa: E402
from simcast.gui import SimCastWindow       # noqa: E402

SHOTS = os.environ.get("SIMCAST_SHOTS")
cfg = dict(DEFAULTS, tts="off", driver_name="Sam Carter")
cast = SimCast(sc, cfg, log=lambda m: None, booth=False, save=False)
cast._simcoach_t = 1e18
win = SimCastWindow(cast, sc)
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
sw.voice_boxes["analyst"].set("en-IE-EmilyNeural")
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
      cast.cfg["analyst_voice"] == "en-IE-EmilyNeural", "settings: saved")
sw2 = win.open_settings() or win.settings_win
sw2.v["tts"][0].set("OpenAI voices (most lifelike, uses your key)")
pump(0.3)
check(sw2.voice_boxes["lead"].cget("values")[0] == "ash", "settings: OpenAI voices offered for OpenAI speech")
sw2.win.destroy()
check(cast.cfg["tts"] == "off", "settings: cancel changes nothing")

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

"""The real app window (needs a display; on Linux run under xvfb-run): Settings and AI provider switching,
the welcome box, old personalities, the setup sheet's confirm/cancel, the overlay's SETUP button and menu,
the phone page (loopback only) and the update banner (faked release, no network)."""
import json
import os
import sys
import threading
import time
import types
import urllib.request

from _common import check, done, load

sc = load()
saved = {}
sc.save_config = lambda c: saved.update(json.loads(json.dumps({k: v for k, v in c.items() if k != "buttons"})))
cfg = sc.load_config()
cfg.update(auto_start=False, gemini_api_key="gk", ai_provider="gemini", coach_personality="perel",
           second_screen=True, second_screen_port=8799)
orig_start = sc.SecondScreen.start
sc.SecondScreen.start = lambda self, port, host="0.0.0.0": orig_start(self, port, "127.0.0.1")   # tests: loopback only
FAKE = {"tag": "v99.0", "version": "99.0", "url": "https://example.invalid/release", "notes": "",
        "installer_url": "https://example.invalid/SimCoach-Setup.exe"}
sc.check_latest_release = lambda timeout=8.0: FAKE
app = sc.App(cfg, voice_on=False, mic_on=False)
root = app.root
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def pump(secs=0.3):
    end = time.time() + secs
    while time.time() < end:
        root.update()
        app._pump()
        root.update()
        time.sleep(0.02)


def wait_for(cond, secs=15):
    end = time.time() + secs
    while time.time() < end and not cond():
        pump(0.1)
    return cond()


def run():
    try:
        # welcome box (new user, no name)
        tops = [w for w in root.winfo_children() if w.winfo_class() == "Toplevel" and w.title() == "Welcome to SimCoach"]
        check(bool(tops), "welcome box on first launch")
        if tops:
            def walk(w):
                for c in w.winfo_children():
                    yield c
                    yield from walk(c)
            ent = [c for c in walk(tops[0]) if c.winfo_class() == "TEntry"][0]
            ent.insert(0, "Sam")
            ent.event_generate("<Return>")
            pump()
            check(cfg["driver_name"] == "Sam" and app.vars["driver_name"].get() == "Sam" and saved.get("name_asked"),
                  "welcome box saves the name")
        # settings: provider switching and saving
        check(app.vars["ai_provider"].get() == "Google Gemini" and app.model_combo.get() == "gemini-3.5-flash", "Gemini shown")
        check(app.vars["coach_personality"].get().startswith("Exit"), "old personality key shows its new name")
        app.vars["ai_provider"].set("DeepSeek")
        for w in app.model_combo.master.winfo_children():
            if "textvariable" in w.keys() and str(w.cget("textvariable")) == str(app.vars["ai_provider"]):
                w.event_generate("<<ComboboxSelected>>")
        pump()
        check(app.model_combo.get() == "deepseek-chat", "switching provider swaps the model list")
        app.vars["deepseek_api_key"].set("dk")
        app.save_settings(quiet=True)
        check(saved.get("ai_provider") == "deepseek" and saved.get("deepseek_api_key") == "dk", "settings saved")
        # update banner (faked release)
        check(wait_for(lambda: getattr(app, "update_bar", None) is not None), "update banner appears")
        app._skip_update()
        check(getattr(app, "update_bar", None) is None and saved.get("update_skip") == "v99.0", "Not now hides and remembers")
        # setup sheet confirm / cancel
        items = [("Aero", "Rear wing", "-1 click"), ("Brakes", "Brake bias", "55.2 %")]
        sheet = {"items": items, "applied": [], "title": "Test Ring · Test Car", "sim": "TEST", "strategist": "x",
                 "coach": "y", "source": "Built-in advisor", "made": "now"}
        app.coach.last_setup_sheet = sheet
        w = sc.SetupSheetWindow(app.root, sheet, font=app._font)
        w._confirm = lambda text: False
        w.apply_all()
        check(not sheet.get("applied"), "Apply all cancelled -> nothing applied")
        w._confirm = lambda text: True
        w.apply_all()
        check(sorted(sheet.get("applied") or []) == [0, 1], "Apply all confirmed -> all applied")
        w.close()
        # overlay SETUP button + menu
        app.toggle_overlay()
        pump()
        ov, cv = app.overlay_win, app.ov_cv
        bx, by = [int(v) for v in cv.coords(cv.find_withtag("setup_btn")[-1])]

        def tap(x, y, dx=0):
            cv.event_generate("<Motion>", x=x, y=y, warp=True)
            pump(0.1)
            cv.event_generate("<ButtonPress-1>", x=x, y=y, rootx=ov.winfo_rootx() + x, rooty=ov.winfo_rooty() + y)
            cv.event_generate("<ButtonRelease-1>", x=x + dx, y=y, rootx=ov.winfo_rootx() + x + dx, rooty=ov.winfo_rooty() + y)
            pump()
        tap(bx, by)
        check(app._sheet_open(), "overlay SETUP opens the sheet")
        tap(bx, by)
        check(not app._sheet_open(), "tapping again closes it")
        tap(bx, by, dx=40)
        check(not app._sheet_open(), "a drag from SETUP doesn't open it")
        labels = []

        class FakeMenu:
            def __init__(self, *a, **k):
                pass

            def add_command(self, label, command):
                labels.append(label)

            def add_separator(self):
                pass

            def tk_popup(self, *a):
                pass
        real, app.tk.Menu = app.tk.Menu, FakeMenu
        app._ov_menu(types.SimpleNamespace(x_root=0, y_root=0))
        app.tk.Menu = real
        check("Show / hide setup sheet" in labels, "overlay menu has the setup sheet item")
        # phone page
        url = "http://127.0.0.1:8799/" + app.screen.url().split(":8799/", 1)[1]
        check(b"<title>SimCoach live</title>" in opener.open(url, timeout=5).read(), "phone page served at the secret address")
        d = json.loads(opener.open(url + "data.json", timeout=5).read())
        check(d.get("version") == sc.APP_VERSION, "phone page data")
        try:
            opener.open("http://127.0.0.1:8799/data.json", timeout=3)
            check(False, "plain address refused")
        except Exception as e:
            check(getattr(e, "code", None) == 404, "plain address refused")
        app.vars["second_screen"].set(False)
        app.save_settings(quiet=True)
        pump()
        try:
            opener.open(url, timeout=3)
            check(False, "switching the phone screen off stops it")
        except Exception:
            check(True, "switching the phone screen off stops it")
    except Exception:
        import traceback
        traceback.print_exc()
        check(False, "no errors")
    finally:
        try:
            done()
        except SystemExit as e:
            os._exit(e.code)


root.after(1500, run)
app.run()

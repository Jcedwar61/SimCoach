"""The real app window (needs a display; on Linux run under xvfb-run): Settings and AI provider switching,
the welcome box, old personalities, the setup sheet's confirm/cancel, the overlay's SETUP button and menu,
the phone page (loopback only), the update banner (faked release, no network) and the Best laps tab."""
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
import tempfile                                                         # noqa: E402
sc.REF_DIR, sc.BEST_DIR = tempfile.mkdtemp(), os.path.join(tempfile.mkdtemp(), "Best laps")
_r = sc.starter_reference("Spa", "gt3")
LAP = {"key": ["ACC", "spa", "porsche_992_gt3_r"], "ref": _r["ref"], "best_time": 138.2,
       "corners": [list(c) for c in _r["corners"]], "best_corner": {str(k): v for k, v in _r["best_corner"].items()},
       "saved": "2026-11-12 10:00", "provisional": False, "source": "own"}
LAPNAME = sc.library_file_name(LAP["key"])
json.dump(LAP, open(os.path.join(sc.REF_DIR, LAPNAME), "w"))
sc.list_library = lambda *a, **k: []
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
        check(app.vars["briefing_mode"].get() == "Full once a day, then short" and app.vars["sheet_autopop"].get(),
              "briefing settings shown with their defaults")
        app.vars["briefing_mode"].set("Full every session")
        app.vars["sheet_autopop"].set(False)
        app.save_settings(quiet=True)
        check(saved.get("briefing_mode") == "always" and saved.get("sheet_autopop") is False, "briefing settings saved")
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
        # Best laps tab: saved ready to share, the web-page route without in-app sign-in, then in-app sharing
        app.nb.select(app.tab_best)
        pump(0.5)
        check(app.best_tv.exists(LAPNAME) and app.best_tv.set(LAPNAME, "status") == "Not shared",
              "best lap listed, not shared yet")
        check(os.path.exists(os.path.join(sc.BEST_DIR, LAPNAME)), "and saved in the Best laps folder")
        opened = []
        app._open = lambda t: opened.append(t)
        cid, sc.GITHUB_CLIENT_ID = sc.GITHUB_CLIENT_ID, ""
        app.share_best([LAPNAME])
        sc.GITHUB_CLIENT_ID = cid
        check(any("upload/main/references" in str(o) for o in opened) and "Drag" in app.best_lbl.cget("text"),
              "no sign-in set up: GitHub upload page with the file's folder")
        import tkinter.messagebox as mb
        mb.askyesno = lambda *a, **k: True
        cfg["github_client_id"], cfg["github_token"], cfg["github_login"] = "cid", "tok", "Sam"
        sc.upload_library_lap = lambda token, name, data, title, **k: ("proposed", "https://example.invalid/pull/1")
        app.share_best([LAPNAME])
        wait_for(lambda: app.best_tv.exists(LAPNAME) and app.best_tv.set(LAPNAME, "status").startswith("Sent"), 5)
        check(app.best_tv.set(LAPNAME, "status") == "Sent · being checked", "shared from the app: being checked")
        check(saved.get("shared_laps", {}).get(LAPNAME, {}).get("url") == "https://example.invalid/pull/1",
              "remembered with its link")
        app._lib_index = {LAPNAME: sc.git_blob_sha(open(os.path.join(sc.BEST_DIR, LAPNAME), "rb").read())}
        app.load_best()
        check(app.best_tv.set(LAPNAME, "status") == "In the library ✓", "added: in the library")
        # Phone screen button: the dialog shows the address and a QR code, and can switch it off and on
        app.phone_screen_dialog()
        pump(0.3)
        dlg = app._phone_dlg

        def kids(w):
            for c in w.winfo_children():
                yield c
                yield from kids(c)
        entries = [c for c in kids(dlg) if c.winfo_class() == "Entry" and c.winfo_manager()]
        check(entries and entries[0].get() == app.screen.url() and app.screen.token in entries[0].get(),
              "phone screen dialog shows the address")
        qrs = [c for c in kids(dlg) if c.winfo_class() == "Canvas" and c.winfo_manager()]
        check(qrs and len(qrs[0].find_all()) > 100, "with a QR code to scan")
        btn = {c.cget("text"): c for c in kids(dlg) if c.winfo_class() == "TButton"}
        btn["Turn off"].invoke()
        pump(0.3)
        check(not app.screen.running() and not cfg["second_screen"] and not app.vars["second_screen"].get(),
              "Turn off stops it and unticks the setting")
        btn = {c.cget("text"): c for c in kids(dlg) if c.winfo_class() == "TButton"}
        btn["Turn on"].invoke()
        pump(0.3)
        check(app.screen.running() and saved.get("second_screen") is True, "Turn on starts it and saves the setting")
        btn = {c.cget("text"): c for c in kids(dlg) if c.winfo_class() == "TButton"}
        btn["Close"].invoke()
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

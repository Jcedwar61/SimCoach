"""SimCast's Windows desktop window: the timing tower, what the booth is saying, the controls and the settings,
plus an optional captions window that floats on top (for a second screen, or to capture in OBS)."""
from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

from . import providers
from .app import APP_DIR, APP_NAME, APP_VERSION, DEFAULTS
from .audio import VOICE_LABEL, VOICES
from .guide import TOPICS as GUIDE

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
ICO = os.path.join(os.path.dirname(HERE), "SimCast.ico")
LICENSE_DIR = os.path.join(HERE, "licenses")

P = {"bg": "#090b10", "panel": "#11151d", "panel2": "#171c26", "line": "#252d3b", "fg": "#e9eef5",
     "mut": "#8b97a9", "cyan": "#2ee0f5", "red": "#ff3347", "red_dk": "#c81d30", "amber": "#ff8c2b",
     "purple": "#b46cff", "green": "#3ddc84", "hover": "#1f2633", "me": "#0f3440", "e3": "#2a1219"}
WHO_COLOUR = {"lead": P["cyan"], "analyst": P["red"], "pit": "#f2f2f2"}
CHATTER_LABELS = {"quiet": "Quiet", "normal": "Normal", "chatty": "Chatty"}
FOCUS_LABELS = {"field": "Whole field", "balanced": "Balanced", "me": "Mostly me"}
PROVIDERS = {"openai": "OpenAI", "gemini": "Google Gemini", "deepseek": "DeepSeek"}


def _dpi_aware():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SimCast.App")
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def dark_titlebar(win):
    """Windows 10/11: a dark title bar, and on Windows 11 a caption and border in SimCast's colours."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4) == 0:
                break

        def rgb(h):
            return ctypes.c_int(int(h[5:7], 16) << 16 | int(h[3:5], 16) << 8 | int(h[1:3], 16))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(rgb(P["bg"])), 4)
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(rgb(P["line"])), 4)
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(rgb(P["fg"])), 4)
    except Exception:
        pass


def _gap_text(s, i, session):
    if i == 0:
        return "Leader" if session == "race" else (_lap(s["best"]) if s["best"] else "")
    if s["status"] in ("dnf", "dsq"):
        return "OUT"
    if session != "race":
        return f"+{s['gap']:.3f}" if s["gap"] is not None else ("" if s["best"] else "no time")
    if s["interval"] is not None:
        return f"+{s['interval']:.1f}"
    if s["laps_down"]:
        return f"+{s['laps_down']} L"
    return ""


def _lap(t):
    m, sec = divmod(t, 60)
    return f"{int(m)}:{sec:06.3f}" if m else f"{sec:.3f}"


class SimCastWindow:
    POLL_MS = 400

    def __init__(self, cast, start_demo=False):
        _dpi_aware()
        self.cast = cast
        self.root = r = tk.Tk(className="SimCast")
        r.title(f"{APP_NAME} {APP_VERSION}")
        r.configure(bg=P["bg"])
        r.minsize(880, 560)
        geo = cast.cfg.get("window")
        r.geometry(geo if isinstance(geo, str) and "x" in geo else "1180x760")
        self._fonts()
        self._style()
        self._icons()
        self._build()
        dark_titlebar(r)
        self.last_line_t = 0.0
        self.captions = None
        self.settings_win = None
        self.stop = threading.Event()
        self.loop = threading.Thread(target=cast.run, args=(self.stop,), daemon=True, name="simcast-loop")
        r.protocol("WM_DELETE_WINDOW", self.close)
        if start_demo:
            cast.start_demo()
        if cast.cfg.get("captions"):
            self.toggle_captions(True)
        if not cast.cfg.get("guide_seen"):                 # first start: open the guide on Getting started
            r.after(600, self.open_guide)
            cast.update_settings({"guide_seen": True})

    # ------------------------------------------------------------------ look
    def _fonts(self):
        import tkinter.font as tkfont
        fams = set(tkfont.families(self.root))
        ui = next((f for f in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica", "DejaVu Sans")
                   if f in fams), "TkDefaultFont")
        head = next((f for f in ("Segoe UI Variable Display", "Segoe UI Semibold", ui) if f in fams), ui)
        self.f = {"ui": (ui, 10), "uib": (ui, 10, "bold"), "small": (ui, 9), "smallb": (ui, 8, "bold"),
                  "title": (head, 18, "bold italic"), "h1": (head, 17, "bold"), "tower": (ui, 11),
                  "towerb": (ui, 11, "bold"), "line": (ui, 11), "line2": (ui, 11, "bold"),
                  "line3": (head, 13, "bold"), "who": (ui, 8, "bold"), "cap": (head, 18, "bold"),
                  "capwho": (ui, 9, "bold")}

    def _style(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure(".", background=P["bg"], foreground=P["fg"], fieldbackground=P["panel2"], font=self.f["ui"],
                     bordercolor=P["line"], lightcolor=P["line"], darkcolor=P["line"], troughcolor=P["panel"],
                     focuscolor=P["red"], selectbackground=P["red_dk"], selectforeground="#fff",
                     insertcolor=P["fg"])
        st.configure("TFrame", background=P["bg"])
        st.configure("Card.TFrame", background=P["panel"])
        st.configure("TLabel", background=P["bg"], foreground=P["fg"])
        st.configure("Card.TLabel", background=P["panel"], foreground=P["fg"])
        st.configure("Mut.TLabel", background=P["bg"], foreground=P["mut"])
        st.configure("CardMut.TLabel", background=P["panel"], foreground=P["mut"], font=self.f["smallb"])
        st.configure("TButton", background=P["panel2"], foreground=P["fg"], borderwidth=1, padding=(12, 6),
                     relief="flat", font=self.f["uib"])
        st.map("TButton", background=[("active", P["hover"]), ("disabled", P["panel"])],
               foreground=[("disabled", P["mut"])])
        st.configure("Accent.TButton", background=P["red_dk"], foreground="#fff", bordercolor=P["red"])
        st.map("Accent.TButton", background=[("active", P["red"])])
        st.configure("OnAir.TButton", foreground=P["red"])
        st.configure("OffAir.TButton", foreground=P["mut"])
        st.configure("Small.TButton", padding=(8, 3), font=self.f["small"])
        st.configure("Tower.Treeview", background=P["panel"], fieldbackground=P["panel"], foreground=P["fg"],
                     rowheight=30, borderwidth=0, font=self.f["tower"])
        st.layout("Tower.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.map("Tower.Treeview", background=[("selected", P["panel2"])], foreground=[("selected", P["fg"])])
        st.configure("TNotebook", background=P["panel"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        st.configure("TNotebook.Tab", background=P["bg"], foreground=P["mut"], padding=(16, 7), borderwidth=0)
        st.map("TNotebook.Tab", background=[("selected", P["panel"])], foreground=[("selected", P["fg"])])
        st.configure("TEntry", fieldbackground=P["panel2"], foreground=P["fg"], padding=5)
        st.configure("TCombobox", fieldbackground=P["panel2"], background=P["panel2"], foreground=P["fg"],
                     arrowcolor=P["fg"], padding=4)
        st.map("TCombobox", fieldbackground=[("readonly", P["panel2"])], foreground=[("readonly", P["fg"])],
               selectbackground=[("readonly", P["panel2"])], selectforeground=[("readonly", P["fg"])])
        self.root.option_add("*TCombobox*Listbox.background", P["panel2"])
        self.root.option_add("*TCombobox*Listbox.foreground", P["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", P["red_dk"])
        for w in ("TRadiobutton", "TCheckbutton"):
            st.configure(w, background=P["panel"], foreground=P["fg"], indicatorbackground=P["panel2"],
                         indicatorforeground=P["panel2"], upperbordercolor=P["line"], lowerbordercolor=P["line"],
                         indicatormargin=(0, 0, 6, 0))
            st.map(w, indicatorbackground=[("selected", P["red"]), ("active", P["hover"])],
                   indicatorforeground=[("selected", "#ffffff")], background=[("active", P["panel"])])
        st.configure("Bar.TCheckbutton", background=P["bg"])
        st.map("Bar.TCheckbutton", background=[("active", P["bg"])])
        st.configure("Horizontal.TScale", background=P["red_dk"], troughcolor=P["panel2"], bordercolor=P["line"],
                     lightcolor=P["red"], darkcolor=P["red_dk"], sliderlength=18)
        st.map("Horizontal.TScale", background=[("active", P["red"])])
        st.configure("Vertical.TScrollbar", background=P["panel2"], troughcolor=P["panel"], arrowcolor=P["mut"],
                     bordercolor=P["panel"], lightcolor=P["panel2"], darkcolor=P["panel2"], gripcount=0,
                     arrowsize=12)
        st.map("Vertical.TScrollbar", background=[("active", P["line"])])

    def _img(self, name):
        try:
            return tk.PhotoImage(file=os.path.join(ASSETS, name))
        except Exception:
            return None

    def _icons(self):
        self.img_logo = self._img("logo-40.png")
        self.img_hero = self._img("hero-car-240.png")
        self.img_helmet = self._img("helmet-32.png")
        icon = self._img("icon-48.png")
        if icon is not None:
            self.root.iconphoto(True, icon)
            self._icon = icon
        if sys.platform == "win32" and os.path.exists(ICO):
            try:
                self.root.iconbitmap(default=ICO)
            except Exception:
                pass

    # ------------------------------------------------------------------ layout
    def _build(self):
        r = self.root
        r.columnconfigure(0, weight=1)
        r.rowconfigure(1, weight=1)

        hdr = ttk.Frame(r, padding=(16, 10))
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.columnconfigure(4, weight=1)
        if self.img_logo:
            ttk.Label(hdr, image=self.img_logo).grid(row=0, column=0, padx=(0, 10))
        brand = tk.Frame(hdr, bg=P["bg"])
        brand.grid(row=0, column=1, padx=(0, 14))
        tk.Label(brand, text="Sim", font=self.f["title"], fg=P["fg"], bg=P["bg"], padx=0, bd=0).pack(side="left")
        tk.Label(brand, text="Cast", font=self.f["title"], fg=P["red"], bg=P["bg"], padx=0, bd=0).pack(side="left")
        pill = tk.Frame(hdr, bg=P["panel"], highlightthickness=1, highlightbackground=P["line"])
        pill.grid(row=0, column=2, padx=(0, 12))
        self.dot = tk.Canvas(pill, width=12, height=12, bg=P["panel"], highlightthickness=0)
        self.dot.pack(side="left", padx=(10, 4), pady=5)
        self.dot_id = self.dot.create_oval(2, 2, 11, 11, fill=P["mut"], outline="")
        self.status = tk.Label(pill, text="Starting…", font=self.f["uib"], fg=P["fg"], bg=P["panel"])
        self.status.pack(side="left", padx=(0, 10))
        self.session = ttk.Label(hdr, text="", style="Mut.TLabel")
        self.session.grid(row=0, column=3, sticky="w")
        btns = ttk.Frame(hdr)
        btns.grid(row=0, column=5, sticky="e")
        self.demo_btn = ttk.Button(btns, text="▶  Demo race", command=self.toggle_demo)
        self.demo_btn.pack(side="left", padx=4)
        ttk.Button(btns, text="Skip", command=self.skip).pack(side="left", padx=4)
        self.air_btn = ttk.Button(btns, text="●  On air", style="OnAir.TButton", command=self.toggle_air)
        self.air_btn.pack(side="left", padx=4)
        ttk.Button(btns, text="?  Guide", command=self.open_guide).pack(side="left", padx=4)
        ttk.Button(btns, text="⚙  Settings", command=self.open_settings).pack(side="left", padx=(4, 0))

        self.body = ttk.Frame(r, padding=(16, 4, 16, 8))
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.columnconfigure(0, weight=0, minsize=330)
        self.body.columnconfigure(1, weight=1)
        self.body.rowconfigure(0, weight=1)

        # timing tower
        tw = ttk.Frame(self.body, style="Card.TFrame", padding=(0, 0, 0, 6))
        tw.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        tw.rowconfigure(1, weight=1)
        tw.columnconfigure(0, weight=1)
        th = ttk.Frame(tw, style="Card.TFrame", padding=(14, 10))
        th.grid(row=0, column=0, sticky="ew")
        ttk.Label(th, text="T I M I N G", style="CardMut.TLabel").pack(side="left")
        self.tower_info = ttk.Label(th, text="", style="CardMut.TLabel")
        self.tower_info.pack(side="right")
        self.tree = ttk.Treeview(tw, style="Tower.Treeview", columns=("pos", "name", "gap"), show="",
                                 selectmode="none")
        self.tree.column("#0", width=0, stretch=False)
        self.tree.column("pos", width=44, anchor="e", stretch=False)
        self.tree.column("name", width=190, anchor="w")
        self.tree.column("gap", width=84, anchor="e", stretch=False)
        self.tree.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        self.tree.tag_configure("me", background=P["me"], foreground=P["cyan"])
        self.tree.tag_configure("battle", foreground=P["amber"])
        self.tree.tag_configure("out", foreground=P["mut"])
        self.tree.tag_configure("top", font=self.f["towerb"])

        # the booth
        bo = ttk.Frame(self.body, style="Card.TFrame")
        bo.grid(row=0, column=1, sticky="nsew")
        bo.rowconfigure(1, weight=1)
        bo.columnconfigure(0, weight=1)
        bh = ttk.Frame(bo, style="Card.TFrame", padding=(14, 10))
        bh.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(bh, text="T H E   B O O T H", style="CardMut.TLabel").pack(side="left")
        self.speaking = tk.Label(bh, text="", font=self.f["smallb"], fg=P["cyan"], bg=P["panel"])
        self.speaking.pack(side="right")
        self.text = tk.Text(bo, bg=P["panel"], fg=P["fg"], relief="flat", wrap="word", font=self.f["line"],
                            padx=16, pady=6, highlightthickness=0, borderwidth=0, cursor="arrow",
                            spacing1=4, spacing3=8, tabs=(96,), state="disabled")
        self.text.grid(row=1, column=0, sticky="nsew")
        sb = ttk.Scrollbar(bo, orient="vertical", command=self.text.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.text.configure(yscrollcommand=sb.set)
        for who, col in WHO_COLOUR.items():
            self.text.tag_configure("who_" + who, foreground=col, font=self.f["who"])
        self.text.tag_configure("e0", font=self.f["line"])
        self.text.tag_configure("e1", font=self.f["line"])
        self.text.tag_configure("e2", font=self.f["line2"])
        self.text.tag_configure("e3", font=self.f["line3"], background=P["e3"])
        self.text.tag_configure("para", lmargin1=0, lmargin2=96)
        self.text.tag_configure("hint", foreground=P["mut"])
        self._text_insert([("The commentary appears here as it's spoken.", "hint")])

        # off-air card (shown instead of the tower and booth when nothing's running)
        self.hero = ttk.Frame(r, style="Card.TFrame", padding=30)
        if self.img_hero:
            ttk.Label(self.hero, image=self.img_hero, style="Card.TLabel").grid(row=0, column=0, rowspan=3,
                                                                                 padx=(0, 30))
        ttk.Label(self.hero, text="Waiting for the green flag", style="Card.TLabel",
                  font=self.f["h1"]).grid(row=0, column=1, sticky="sw")
        ttk.Label(self.hero, style="Card.TLabel", foreground=P["mut"], wraplength=520, justify="left",
                  text="Start a race in Le Mans Ultimate, rFactor 2, iRacing, Automobilista 2, RaceRoom, F1 25 or "
                       "Assetto Corsa (with the CrewChiefEx app) and the booth goes on air by itself.\n\n"
                       "Or hear what it sounds like right now with a demo race."
                  ).grid(row=1, column=1, sticky="w", pady=(8, 14))
        ttk.Button(self.hero, text="▶  Start a demo race", style="Accent.TButton",
                   command=self.toggle_demo).grid(row=2, column=1, sticky="nw")
        ttk.Label(self.hero, text="S I M S   O N   T H I S   P C", style="CardMut.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(26, 6))
        self.sims_box = ttk.Frame(self.hero, style="Card.TFrame")
        self.sims_box.grid(row=4, column=0, columnspan=2, sticky="w")
        self._sims_shown = None

        foot = ttk.Frame(r, padding=(16, 0, 16, 10))
        foot.grid(row=2, column=0, sticky="ew")
        foot.columnconfigure(0, weight=1)
        self.foot = ttk.Label(foot, text="", style="Mut.TLabel")
        self.foot.grid(row=0, column=0, sticky="w")
        self.cap_var = tk.BooleanVar(value=bool(self.cast.cfg.get("captions")))
        ttk.Checkbutton(foot, text="Captions window", style="Bar.TCheckbutton", variable=self.cap_var,
                        command=lambda: self.toggle_captions(self.cap_var.get())).grid(row=0, column=1, sticky="e")
        self._idle_shown = None

    def _show_idle(self, idle):
        if idle == self._idle_shown:
            return
        self._idle_shown = idle
        if idle:
            self.body.grid_remove()
            self.hero.grid(row=1, column=0, sticky="nsew", padx=16, pady=(4, 8))
        else:
            self.hero.grid_remove()
            self.body.grid()

    # ------------------------------------------------------------------ live updates
    def _text_insert(self, parts):
        t = self.text
        at_end = t.yview()[1] > 0.98
        t.configure(state="normal")
        for txt, tag in parts:
            t.insert("end", txt, tag)
        lines = int(t.index("end-1c").split(".")[0])
        if lines > 600:
            t.delete("1.0", f"{lines - 500}.0")
        t.configure(state="disabled")
        if at_end:
            t.see("end")

    def poll(self):
        try:
            self._render(self.cast.state())
        except Exception as e:
            self.foot.configure(text=f"Display error: {e}")
        self.root.after(self.POLL_MS, self.poll)

    def _render(self, S):
        live, demo = bool(S["source"]) and not S["demo"], S["demo"]
        colour = P["red"] if live else P["amber"] if demo else P["mut"]
        if live and int(time.time() * 2) % 3 == 0:
            colour = "#7a1a24"                                  # the live dot pulses
        self.dot.itemconfigure(self.dot_id, fill=colour)
        self.status.configure(text=S["status"])
        ses = ""
        if S["track"]:
            ses = S["track"]
            if S["session"] == "race" and S["lap"]:
                ses += f"  ·  Lap {S['lap']}" + (f" / {S['laps']}" if S["laps"] else "")
            elif S["session"]:
                ses += f"  ·  {S['session'].capitalize()}"
            if S["flag"]:
                ses += f"  ·  {S['flag'].upper()}"
            if S["finished"]:
                ses += "  ·  Chequered flag"
        self.session.configure(text=ses)
        self.demo_btn.configure(text="■  Stop demo" if demo else "▶  Demo race")
        self.air_btn.configure(text="●  On air" if S["on_air"] else "○  Off air",
                               style="OnAir.TButton" if S["on_air"] else "OffAir.TButton")
        self._show_idle(not S["source"] and not demo)
        self._render_sims(S.get("sims") or [])

        rows = S["standings"]
        kids = self.tree.get_children()
        for iid in kids[len(rows):]:
            self.tree.delete(iid)
        for i, s in enumerate(rows):
            name = s["call"]
            if s["in_pit"]:
                name += "   PIT"
            if s["status"] == "stopped":
                name += "   STOPPED"
            if s["status"] == "finished":
                name += "   🏁"
            if s["fastest"]:
                name += "   ⏱"
            tags = (("me",) if s["player"] else ()) + (("battle",) if s["battle"] and not s["player"] else ()) + \
                (("out",) if s["status"] in ("dnf", "dsq") else ()) + (("top",) if i < 3 else ())
            vals = (s["pos"], name, _gap_text(s, i, S["session"]))
            iid = f"r{i}"
            if iid in kids:
                if self.tree.item(iid, "values") != tuple(str(v) for v in vals) or self.tree.item(iid, "tags") != tags:
                    self.tree.item(iid, values=vals, tags=tags)
            else:
                self.tree.insert("", "end", iid=iid, values=vals, tags=tags)
        self.tower_info.configure(text=f"{len(rows)} CARS" if rows else "")

        new = [ln for ln in S["lines"] if ln["t"] > self.last_line_t]
        if new:
            if self.last_line_t == 0.0:
                self.text.configure(state="normal")
                self.text.delete("1.0", "end")
                self.text.configure(state="disabled")
            parts = []
            for ln in new:
                parts += [(ln["name"].upper() + "\t", ("who_" + ln["who"], "para")),
                          (ln["text"] + "\n", ("e%d" % ln["energy"], "para"))]
                self.last_line_t = ln["t"]
            self._text_insert(parts)
            if self.captions is not None:
                self.captions.show(new[-1])
        self.speaking.configure(text="● SPEAKING" if S["speaking"] else "")
        if self.captions is not None and not S["speaking"]:
            self.captions.idle()

        st = S["settings"]
        bits = []
        if S["ai"]:
            bits.append(f"AI booth: {S['ai']}")
        elif st.get("ai_colour"):
            bits.append("AI booth: no key, using the built-in lines")
        if S["voice_note"]:
            bits.append(S["voice_note"])
        if S["errors"]:
            bits.append(S["errors"][-1])
        self.foot.configure(text="   ·   ".join(bits))

    def _render_sims(self, sims):
        key = tuple((s["name"], s["status"], s["ok"]) for s in sims)
        if key == self._sims_shown:
            return
        self._sims_shown = key
        sims_list(self.sims_box, sims, self.f)

    # ------------------------------------------------------------------ actions
    def toggle_demo(self):
        if self.cast.demo is not None:
            self.cast.stop_demo()
        else:
            self.cast.start_demo()
        self.last_line_t = 0.0 if not self.cast.lines else self.last_line_t

    def skip(self):
        self.cast.audio.interrupt(None)

    def toggle_air(self):
        d = self.cast.director
        d.on_air = not d.on_air
        if not d.on_air:
            self.cast.audio.interrupt(None)

    def toggle_captions(self, on):
        if on and self.captions is None:
            self.captions = Captions(self)
            if self.cast.lines:
                self.captions.show(self.cast.lines[-1])          # the latest line straight away
        elif not on and self.captions is not None:
            self.captions.close()
            self.captions = None
        self.cap_var.set(bool(on))
        if bool(self.cast.cfg.get("captions")) != bool(on):
            self.cast.update_settings({"captions": bool(on)})

    def open_guide(self, topic=None):
        g = getattr(self, "guide_win", None)
        if g is not None and g.win.winfo_exists():
            g.win.lift()
            if topic:
                names = [t for t, _ in g.topics]
                g.show(names.index(topic) if topic in names else 0)
            return
        self.guide_win = GuideWindow(self, topic)

    def open_settings(self):
        if self.settings_win is not None and self.settings_win.win.winfo_exists():
            self.settings_win.win.lift()
            return
        self.settings_win = SettingsWindow(self)

    def run(self):
        self.loop.start()
        self.root.after(100, self.poll)
        self.root.mainloop()

    def close(self):
        try:
            g = self.root.geometry().split("+")[0]
            if self.root.state() == "normal" and g != self.cast.cfg.get("window"):
                self.cast.update_settings({"window": g})
        except Exception:
            pass
        self.stop.set()
        try:
            self.cast.audio.interrupt(None)
        except Exception:
            pass
        self.root.destroy()


class Captions:
    """A small always-on-top window with the line being spoken: for a second screen, or a window capture in OBS."""

    def __init__(self, app):
        self.app = app
        f = app.f
        self.win = w = tk.Toplevel(app.root)
        w.title("SimCast captions")
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=P["bg"])
        pos = app.cast.cfg.get("captions_pos")
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        x, y = (pos if isinstance(pos, list) and len(pos) == 2 else (sw // 2 - 450, sh - 220))
        w.geometry(f"900x110+{int(x)}+{int(y)}")
        self.bar = tk.Frame(w, bg=P["cyan"], width=6)
        self.bar.pack(side="left", fill="y")
        inner = tk.Frame(w, bg=P["bg"], padx=16, pady=10)
        inner.pack(side="left", fill="both", expand=True)
        top = tk.Frame(inner, bg=P["bg"])
        top.pack(fill="x")
        if app.img_helmet:
            tk.Label(top, image=app.img_helmet, bg=P["bg"]).pack(side="left", padx=(0, 8))
        self.who = tk.Label(top, text="SIMCAST", font=f["capwho"], fg=P["mut"], bg=P["bg"])
        self.who.pack(side="left")
        tk.Label(top, text="drag to move · right-click to close", font=f["small"], fg="#3b4556",
                 bg=P["bg"]).pack(side="right")
        self.text = tk.Label(inner, text="", font=f["cap"], fg=P["fg"], bg=P["bg"], wraplength=840, justify="left",
                             anchor="w")
        self.text.pack(fill="both", expand=True)
        self.hide_at = 0.0
        for wd in (w, inner, top, self.text, self.who):
            wd.bind("<ButtonPress-1>", self._grab)
            wd.bind("<B1-Motion>", self._drag)
            wd.bind("<ButtonRelease-1>", self._drop)
            wd.bind("<Button-3>", lambda e: app.toggle_captions(False))

    def show(self, ln):
        self.bar.configure(bg=WHO_COLOUR.get(ln["who"], P["cyan"]))
        self.who.configure(text=ln["name"].upper(), fg=WHO_COLOUR.get(ln["who"], P["mut"]))
        self.text.configure(text=ln["text"], fg=P["fg"])
        self.hide_at = time.monotonic() + 2.0 + len(ln["text"].split()) * 0.38

    def idle(self):
        if self.hide_at and time.monotonic() > self.hide_at:
            self.text.configure(fg="#4a5568")
            self.hide_at = 0.0

    def _grab(self, e):
        self._off = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _drag(self, e):
        self.win.geometry(f"+{e.x_root - self._off[0]}+{e.y_root - self._off[1]}")

    def _drop(self, e):
        self.app.cast.update_settings({"captions_pos": [self.win.winfo_x(), self.win.winfo_y()]})

    def close(self):
        try:
            self.win.destroy()
        except Exception:
            pass


class SettingsWindow:
    """Settings, in five tabs: Commentary, Voices, AI, Sims, About."""

    def __init__(self, app):
        self.app = app
        cast = app.cast
        cfg = cast.config()
        self.win = w = tk.Toplevel(app.root)
        w.title("SimCast settings")
        w.configure(bg=P["panel"])
        w.transient(app.root)
        w.resizable(False, False)
        dark_titlebar(w)
        self.nb = nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True)
        self.v = {}
        self.f = app.f

        def page(title):
            f = ttk.Frame(nb, style="Card.TFrame", padding=18)
            f.columnconfigure(1, weight=1)
            nb.add(f, text=f"  {title}  ")
            return f

        # ---------------------------------------------------------------- Commentary
        f = page("Commentary")
        self.row(f, 0, "How chatty", self.radios(f, "chatter", CHATTER_LABELS, cfg))
        self.row(f, 1, "Follow", self.radios(f, "focus", FOCUS_LABELS, cfg))
        self.row(f, 2, "Your name", self.entry(f, "driver_name", cfg))
        self.note(f, 3, "As the booth should say it. Empty: the name your sim uses.")
        self.row(f, 4, "Pit lane", self.check(f, "pit_reporter", "A pit-lane reporter covers the stops", cfg))
        laps = ttk.Frame(f, style="Card.TFrame")
        self.entry(laps, "demo_laps", cfg, width=5).pack(side="left")
        ttk.Label(laps, text="  laps", style="Card.TLabel", foreground=P["mut"]).pack(side="left")
        self.row(f, 5, "Demo race", laps, sticky="w")

        # ---------------------------------------------------------------- Voices
        f = page("Voices")
        self.row(f, 0, "Speech", self.check(f, "tts", "The booth speaks (off: text only)", cfg, on="on", off="off"))
        self.voice_boxes = {}
        r = 1
        for who, label in (("lead", "Lead commentator"), ("analyst", "Analyst"), ("pit", "Pit-lane reporter")):
            self.row(f, r, label, self.entry(f, f"{who}_name", cfg),
                     ttk.Button(f, text="Test", style="Small.TButton", command=lambda w=who: self.test_voice(w)))
            cb = ttk.Combobox(f, state="readonly", width=44, values=[n for n, _ in VOICES], height=18)
            cb.set(VOICE_LABEL.get(cfg.get(f"{who}_voice"), VOICES[0][0]))
            self.voice_boxes[who] = cb
            self.row(f, r + 1, "   voice", cb)
            r += 2
        outs = []
        try:
            outs = cast.audio.list_outputs() if hasattr(cast.audio, "list_outputs") else []
        except Exception:
            outs = []
        cur_out = cfg.get("audio_out") or ""
        if cur_out and cur_out not in outs:
            outs.append(cur_out)
        self.row(f, r, "Play on", self.combo(f, "audio_out", [""] + outs, {"": "Windows default", **{o: o for o in outs}}, cfg),
                 ttk.Button(f, text="Test", style="Small.TButton", command=lambda: self.test_voice("lead")))
        self.v["volume"] = tk.DoubleVar(value=float(cfg.get("volume", 0.9)))
        self.row(f, r + 1, "Volume", ttk.Scale(f, from_=0, to=1, variable=self.v["volume"]))
        self.v["speech_rate"] = tk.DoubleVar(value=float(cfg.get("speech_rate", 0)))
        self.row(f, r + 2, "Speed", ttk.Scale(f, from_=-20, to=20, variable=self.v["speech_rate"]))
        self.note(f, r + 3, "Microsoft and Google voices need the internet. Kokoro voices run on this PC (a one-time "
                            "download of about 115 MB). OpenAI voices use your OpenAI key and are the most lifelike. "
                            "If a voice can't be reached, the line is spoken by Kokoro, Google or Windows instead.")

        # ---------------------------------------------------------------- AI
        f = page("AI")
        self.note(f, 0, "Without AI the booth calls every moment from its own lines. With a key, the analyst reacts "
                        "with real analysis, quiet spells become conversation, and there's a sign-off at the end. "
                        "Keys stay on this PC.", span=3)
        self.row(f, 1, "AI commentary", self.check(f, "ai_colour", "On", cfg))
        self.row(f, 2, "Use first", self.combo(f, "ai_provider", list(PROVIDERS), PROVIDERS, cfg))
        self.row(f, 3, "", self.check(f, "ai_fallback", "If it's down or out of credit, use another provider with a key", cfg))
        has = cast.state()["settings"]["keys"]
        self.model_boxes = {}
        r = 4
        for p, label in PROVIDERS.items():
            self.row(f, r, f"{label} key", self.entry(f, f"{p}_api_key", cfg, show="•"),
                     ttk.Label(f, text="✓ set" if has.get(f"{p}_api_key") else "", style="Card.TLabel",
                               foreground=P["green"]))
            cb = ttk.Combobox(f, state="readonly", width=44)
            self._fill_models(cb, p, cfg)
            self.model_boxes[p] = cb
            self.row(f, r + 1, "   model", cb)
            r += 2
        tts = ttk.Combobox(f, state="readonly", width=44)
        self._fill_tts(tts, cfg)
        self.tts_box = tts
        self.row(f, r, "OpenAI speech", tts)
        imp = providers.import_simcoach_keys()
        if imp:
            ttk.Button(f, text="Copy keys from SimCoach", style="Small.TButton",
                       command=lambda: self._import(imp)).grid(row=r + 1, column=1, sticky="w", pady=(6, 0))
        st = cast.state()
        ttk.Label(f, style="Card.TLabel", foreground=P["green"] if st["ai"] else P["mut"], wraplength=500,
                  text=(f"Now using: {st['ai']}" if st["ai"] else "No AI key yet: the booth uses its own lines.") +
                       (f"\nLast problem: {st['ai_error']}" if st.get("ai_error") else "")
                  ).grid(row=r + 2, column=0, columnspan=3, sticky="w", pady=(10, 0))

        # ---------------------------------------------------------------- Sims
        f = page("Sims")
        self.row(f, 0, "Game setup", self.check(f, "game_setup", "Switch on what installed sims need, automatically", cfg))
        self.note(f, 1, "EA WRC, DiRT Rally 2.0 and F1 25 telemetry, ACC's broadcasting port and Assetto Corsa's "
                        "CrewChiefEx app (backing up what it changes). Restart a game once after it's been set up.")
        self.row(f, 2, "F1 25 port", self.entry(f, "f1_port", cfg, width=8), sticky="w")
        self.row(f, 3, "SimHub", self.check(f, "udp_share_simhub", "Share UDP port 20777 with SimHub", cfg))
        box = ttk.Frame(f, style="Card.TFrame")
        box.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 4))
        sims_list(box, cast.state().get("sims") or [], self.f, wrap=480)

        def rescan():
            cast.scan_sims(setup=False)
            sims_list(box, cast.state().get("sims") or [], self.f, wrap=480)
        ttk.Button(f, text="Scan again", style="Small.TButton", command=rescan).grid(row=6, column=0, sticky="w",
                                                                                   pady=(4, 8))
        self.note(f, 7, "Whole field: Le Mans Ultimate, rFactor 2, iRacing, Automobilista 2, RaceRoom, F1 25, ACC, "
                        "Assetto Corsa (with the CrewChiefEx app). Your car only: AC EVO, Assetto Corsa without "
                        "CrewChiefEx. Rally stages: EA SPORTS WRC, DiRT Rally 2.0, AC Rally. The Guide has the "
                        "one-time game settings.", span=3)

        # ---------------------------------------------------------------- About
        f = page("About")
        top = ttk.Frame(f, style="Card.TFrame")
        top.grid(row=0, column=0, columnspan=3, sticky="w")
        if app.img_logo:
            ttk.Label(top, image=app.img_logo, style="Card.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(top, text=f"SimCast {APP_VERSION}", style="Card.TLabel", font=self.f["h1"]).pack(side="left")
        self.note(f, 1, "Live TV-style commentary for sim racing. MIT License, Copyright (c) 2026 Jcedwar61. "
                        "SimCast works on its own: SimCoach doesn't need to be installed.", span=3)
        b = ttk.Frame(f, style="Card.TFrame")
        b.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Button(b, text="Guide", style="Small.TButton", command=app.open_guide).pack(side="left", padx=(0, 6))
        ttk.Button(b, text="Licences", style="Small.TButton",
                   command=lambda: app.open_guide("About and licences")).pack(side="left", padx=6)
        ttk.Button(b, text="Open log folder", style="Small.TButton",
                   command=lambda: _open_path(APP_DIR)).pack(side="left", padx=6)

        bb = ttk.Frame(w, style="Card.TFrame", padding=(18, 0, 18, 16))
        bb.pack(fill="x")
        ttk.Button(bb, text="Save", style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(bb, text="Cancel", command=w.destroy).pack(side="right", padx=8)
        w.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - w.winfo_reqwidth()) // 2
        y = app.root.winfo_rooty() + 50
        w.geometry(f"+{max(0, x)}+{max(0, y)}")

    # ---------------------------------------------------------------- widgets
    def row(self, f, r, label, widget, extra=None, sticky="ew"):
        ttk.Label(f, text=label, style="Card.TLabel", foreground=P["mut"]).grid(row=r, column=0, sticky="w",
                                                                               padx=(0, 14), pady=4)
        widget.grid(row=r, column=1, sticky=sticky, pady=4)
        if extra is not None:
            extra.grid(row=r, column=2, sticky="w", padx=(8, 0), pady=4)

    def note(self, f, r, text, span=2):
        ttk.Label(f, text=text, style="Card.TLabel", foreground=P["mut"], font=self.f["small"], wraplength=520,
                  justify="left").grid(row=r, column=0 if span == 3 else 1, columnspan=span, sticky="w", pady=(0, 6))

    def radios(self, f, key, labels, cfg):
        fr = ttk.Frame(f, style="Card.TFrame")
        var = self.v[key] = tk.StringVar(value=cfg.get(key))
        for k, lab in labels.items():
            ttk.Radiobutton(fr, text=lab, value=k, variable=var).pack(side="left", padx=(0, 14))
        return fr

    def entry(self, f, key, cfg, show=None, width=30):
        var = self.v[key] = tk.StringVar(value="" if show else str(cfg.get(key) or ""))
        return ttk.Entry(f, textvariable=var, width=width, show=show or "")

    def check(self, f, key, text, cfg, on=True, off=False):
        var = tk.BooleanVar(value=cfg.get(key) == on)
        self.v[key] = ("check", var, on, off)
        return ttk.Checkbutton(f, text=text, variable=var)

    def combo(self, f, key, values, labels, cfg):
        var = tk.StringVar(value=labels.get(cfg.get(key), cfg.get(key) or ""))
        self.v[key] = (var, {v: k for k, v in labels.items()})
        return ttk.Combobox(f, textvariable=var, values=[labels[x] for x in values], state="readonly", width=44)

    def _fill_models(self, cb, p, cfg):
        best = providers.best_model(cfg, p)
        choices = providers.model_choices(cfg, p)
        labels = [f"Automatic (best: {best})"] + choices
        cb.configure(values=labels)
        cur = cfg.get(f"{p}_model") or providers.AUTO
        cb.set(labels[0] if cur == providers.AUTO or cur not in choices else cur)

    def _fill_tts(self, cb, cfg):
        d = providers.detected(cfg, "openai")
        choices = (d["tts"] if d and d["tts"] else [providers.TTS_FALLBACK])[:8]
        labels = [f"Automatic (best: {providers.tts_model(dict(cfg, openai_tts_model=providers.AUTO))})"] + choices
        cb.configure(values=labels)
        cur = cfg.get("openai_tts_model") or providers.AUTO
        cb.set(labels[0] if cur == providers.AUTO or cur not in choices else cur)

    def _import(self, keys):
        self.app.cast.update_settings(keys)
        self.win.destroy()
        self.app.open_settings()
        self.app.settings_win.nb.select(2)

    def _collect(self):
        out = {}
        for k, var in self.v.items():
            if isinstance(var, tuple) and var[0] == "check":
                out[k] = var[2] if var[1].get() else var[3]
            elif isinstance(var, tuple):
                txt, back = var[0].get(), var[1]
                out[k] = back.get(txt, txt)
            else:
                out[k] = var.get()
        by_label = {n: v for n, v in VOICES}
        for who, cb in self.voice_boxes.items():
            out[f"{who}_voice"] = by_label.get(cb.get(), DEFAULTS[f"{who}_voice"])
        for p, cb in self.model_boxes.items():
            val = cb.get()
            out[f"{p}_model"] = providers.AUTO if val.startswith("Automatic") else val
        val = self.tts_box.get()
        out["openai_tts_model"] = providers.AUTO if val.startswith("Automatic") else val
        for k in ("demo_laps", "f1_port"):
            try:
                out[k] = int(out.get(k) or DEFAULTS[k])
            except ValueError:
                out[k] = DEFAULTS[k]
        out["speech_rate"] = int(round(float(out.get("speech_rate", 0))))
        return out

    def test_voice(self, who):
        self.app.cast.update_settings(self._collect())
        cfg = self.app.cast.config()
        text = {"lead": f"Hello, I'm {cfg.get('lead_name')}, and I'll be calling the action today!",
                "analyst": f"And I'm {cfg.get('analyst_name')}. I'll be telling you what it all means.",
                "pit": f"{cfg.get('pit_name')} here in the pit lane, I'll bring you every stop."}[who]
        audio = self.app.cast.audio
        if hasattr(audio, "preview"):
            audio.preview(who, text, 2)

    def save(self):
        self.app.cast.update_settings(self._collect())
        self.win.destroy()


class GuideWindow:
    """The built-in guide: topics on the left, the page on the right."""

    def __init__(self, app, topic=None):
        self.app = app
        self.win = w = tk.Toplevel(app.root)
        w.title("SimCast guide")
        w.configure(bg=P["bg"])
        w.geometry("980x640")
        w.minsize(720, 460)
        dark_titlebar(w)
        w.columnconfigure(1, weight=1)
        w.rowconfigure(0, weight=1)
        self.topics = list(GUIDE) + [("About and licences", None)]
        side = tk.Frame(w, bg=P["panel"], padx=8, pady=10)
        side.grid(row=0, column=0, sticky="ns")
        self.buttons = []
        for i, (title, _) in enumerate(self.topics):
            b = tk.Label(side, text=title, anchor="w", bg=P["panel"], fg=P["mut"], font=app.f["ui"], padx=12,
                         pady=7, cursor="hand2", width=32)
            b.pack(fill="x")
            b.bind("<Button-1>", lambda e, i=i: self.show(i))
            self.buttons.append(b)
        body = tk.Frame(w, bg=P["panel"])
        body.grid(row=0, column=1, sticky="nsew", padx=(10, 16), pady=16)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.text = tk.Text(body, bg=P["panel"], fg=P["fg"], relief="flat", wrap="word", font=app.f["line"],
                            padx=22, pady=16, highlightthickness=0, borderwidth=0, spacing1=2, spacing3=6,
                            cursor="arrow")
        self.text.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=sb.set)
        self.text.tag_configure("h", font=app.f["h1"], foreground=P["fg"], spacing1=14, spacing3=8)
        self.text.tag_configure("b", lmargin1=8, lmargin2=26)
        self.text.tag_configure("mono", font=("Consolas", 9), foreground=P["mut"])
        names = [t for t, _ in self.topics]
        self.show(names.index(topic) if topic in names else 0)

    def show(self, i):
        for k, b in enumerate(self.buttons):
            b.configure(bg=P["panel2"] if k == i else P["panel"], fg=P["fg"] if k == i else P["mut"])
        title, body = self.topics[i]
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        if body is None:
            self._licences()
        else:
            for line in body.strip().splitlines():
                if line.startswith("## "):
                    t.insert("end", line[3:] + "\n", "h")
                elif line.startswith("- "):
                    t.insert("end", "•  " + line[2:] + "\n", "b")
                elif line.strip():
                    t.insert("end", line + "\n")
        t.configure(state="disabled")
        t.yview_moveto(0)
        self.current = title

    def _licences(self):
        t = self.text
        t.insert("end", f"SimCast {APP_VERSION}\n", "h")
        t.insert("end", "SimCast is free software under the MIT License. It works on its own; SimCoach isn't needed.\n")
        for name, title in (("LICENSE.txt", "SimCast licence (MIT)"), ("THIRD_PARTY_NOTICES.txt", "Third-party notices")):
            t.insert("end", title + "\n", "h")
            try:
                with open(os.path.join(LICENSE_DIR, name), encoding="utf-8") as fh:
                    t.insert("end", fh.read() + "\n", "mono")
            except Exception:
                t.insert("end", f"({name} is missing from this installation)\n", "mono")
        t.insert("end", "Full licence texts referred to above (LGPL-3.0, GPL-3.0) are in the licenses folder of the "
                        "SimCast installation.\n")


def sims_list(box, sims, f, wrap=620):
    """The installed sims, one per line: a green tick when ready, amber when there's something to do."""
    for w in box.winfo_children():
        w.destroy()
    if not sims:
        ttk.Label(box, text="None found yet. SimCast still goes on air as soon as a supported sim is running.",
                  style="Card.TLabel", foreground=P["mut"]).grid(row=0, column=0, sticky="w")
        return
    for i, s in enumerate(sims):
        ttk.Label(box, text="✓" if s["ok"] else "!", style="Card.TLabel", width=2, font=f["uib"],
                  foreground=P["green"] if s["ok"] else P["amber"]).grid(row=i, column=0, sticky="nw")
        ttk.Label(box, text=s["name"], style="Card.TLabel", font=f["uib"], width=26).grid(row=i, column=1, sticky="nw")
        ttk.Label(box, text=s["status"], style="Card.TLabel", foreground=P["mut"], wraplength=wrap,
                  justify="left").grid(row=i, column=2, sticky="nw", pady=1)


def _open_path(path):
    try:
        os.makedirs(path, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)                    # noqa: S606 (opens the folder in Explorer)
    except Exception:
        pass

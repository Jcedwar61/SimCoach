"""SimCast's Windows desktop window: the timing tower, what the booth is saying, the controls and the settings,
plus an optional captions window that floats on top (for a second screen, or to capture in OBS)."""
from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

from .app import APP_NAME, APP_VERSION, DEFAULTS
from .audio import EDGE_VOICES, OPENAI_VOICES

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
ICO = os.path.join(os.path.dirname(HERE), "SimCast.ico")

P = {"bg": "#090b10", "panel": "#11151d", "panel2": "#171c26", "line": "#252d3b", "fg": "#e9eef5",
     "mut": "#8b97a9", "cyan": "#2ee0f5", "red": "#ff3347", "red_dk": "#c81d30", "amber": "#ff8c2b",
     "purple": "#b46cff", "green": "#3ddc84", "hover": "#1f2633", "me": "#0f3440", "e3": "#2a1219"}
WHO_COLOUR = {"lead": P["cyan"], "analyst": P["red"], "pit": "#f2f2f2"}
TTS_LABELS = {"edge": "Microsoft neural voices (free)", "openai": "OpenAI voices (most lifelike, uses your key)",
              "off": "Off (text only)"}
CHATTER_LABELS = {"quiet": "Quiet", "normal": "Normal", "chatty": "Chatty"}
FOCUS_LABELS = {"field": "Whole field", "balanced": "Balanced", "me": "Mostly me"}
PROVIDER_LABELS = {"": "Same as SimCoach", "openai": "OpenAI", "gemini": "Google Gemini", "deepseek": "DeepSeek"}


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

    def __init__(self, cast, sc=None, start_demo=False):
        _dpi_aware()
        self.cast, self.sc = cast, sc
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
        if sc is not None:
            try:
                sc._win_dark_titlebar(r)
            except Exception:
                pass
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
        st.configure("Horizontal.TScale", background=P["panel"], troughcolor=P["panel2"])
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
    def __init__(self, app):
        self.app = app
        cast = app.cast
        cfg = cast.config()
        self.win = w = tk.Toplevel(app.root)
        w.title("SimCast settings")
        w.configure(bg=P["panel"])
        w.transient(app.root)
        w.resizable(False, False)
        if app.sc is not None:
            try:
                app.sc._win_dark_titlebar(w)
            except Exception:
                pass
        nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True)
        self.v = {}

        def page(title):
            f = ttk.Frame(nb, style="Card.TFrame", padding=18)
            f.columnconfigure(1, weight=1)
            nb.add(f, text=title)
            return f

        def row(f, r, label, widget, extra=None, sticky="ew"):
            ttk.Label(f, text=label, style="Card.TLabel", foreground=P["mut"]).grid(row=r, column=0, sticky="w",
                                                                                   padx=(0, 14), pady=5)
            widget.grid(row=r, column=1, sticky=sticky, pady=5)
            if extra is not None:
                extra.grid(row=r, column=2, sticky="w", padx=(8, 0), pady=5)

        def radios(f, key, labels):
            fr = ttk.Frame(f, style="Card.TFrame")
            var = self.v[key] = tk.StringVar(value=cfg.get(key))
            for k, lab in labels.items():
                ttk.Radiobutton(fr, text=lab, value=k, variable=var).pack(side="left", padx=(0, 14))
            return fr

        def entry(f, key, show=None, width=30):
            var = self.v[key] = tk.StringVar(value="" if show else str(cfg.get(key) or ""))
            return ttk.Entry(f, textvariable=var, width=width, show=show or "")

        def combo(f, key, values, labels=None):
            labels = labels or {x: x for x in values}
            var = tk.StringVar(value=labels.get(cfg.get(key), cfg.get(key) or ""))
            self.v[key] = (var, {v: k for k, v in labels.items()})
            return ttk.Combobox(f, textvariable=var, values=[labels[x] for x in values], state="readonly", width=40)

        # commentary
        f = page("  Commentary  ")
        row(f, 0, "How chatty", radios(f, "chatter", CHATTER_LABELS))
        row(f, 1, "Follow", radios(f, "focus", FOCUS_LABELS))
        row(f, 2, "Your name", entry(f, "driver_name"))
        ttk.Label(f, text="As the booth should say it. Empty: your name from SimCoach, or the one your sim uses.",
                  style="Card.TLabel", foreground=P["mut"], font=app.f["small"]).grid(row=3, column=1, sticky="w")
        self.v["pit_reporter"] = tk.BooleanVar(value=bool(cfg.get("pit_reporter", True)))
        row(f, 4, "Pit lane", ttk.Checkbutton(f, text="A pit-lane reporter covers the stops",
                                              variable=self.v["pit_reporter"]))
        laps = ttk.Frame(f, style="Card.TFrame")
        e = entry(laps, "demo_laps", width=5)
        e.pack(side="left")
        ttk.Label(laps, text="  laps", style="Card.TLabel", foreground=P["mut"]).pack(side="left")
        row(f, 5, "Demo race", laps, sticky="w")

        # voices
        f = page("  Voices  ")
        row(f, 0, "Speech", combo(f, "tts", list(TTS_LABELS), TTS_LABELS))
        self.voice_boxes = {}
        r = 1
        for who, label in (("lead", "Lead commentator"), ("analyst", "Analyst"), ("pit", "Pit-lane reporter")):
            row(f, r, label, entry(f, f"{who}_name"),
                ttk.Button(f, text="Test", style="Small.TButton", command=lambda w=who: self.test_voice(w)))
            cb = ttk.Combobox(f, state="readonly", width=40)
            self.voice_boxes[who] = cb
            row(f, r + 1, "   voice", cb)
            r += 2
        self.v["volume"] = tk.DoubleVar(value=float(cfg.get("volume", 0.9)))
        row(f, r, "Volume", ttk.Scale(f, from_=0, to=1, variable=self.v["volume"]))
        outs = []
        try:
            outs = cast.audio.list_outputs() if hasattr(cast.audio, "list_outputs") else []
        except Exception:
            outs = []
        row(f, r + 1, "Play on", combo(f, "audio_out", [""] + outs, {"": "Windows default", **{o: o for o in outs}}))
        self.vnote = ttk.Label(f, text="", style="Card.TLabel", foreground=P["mut"], font=app.f["small"],
                               wraplength=460, justify="left")
        self.vnote.grid(row=r + 2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._fill_voices(cfg)
        self.v["tts"][0].trace_add("write", lambda *a: self._fill_voices(self._collect()))

        # AI
        f = page("  AI colour  ")
        ttk.Label(f, style="Card.TLabel", foreground=P["mut"], wraplength=470, justify="left",
                  text="The booth calls every moment on its own. With an AI key, the analyst also reacts to big "
                       "moments, quiet spells become real conversation about the race, and there's a proper "
                       "sign-off at the end. SimCast uses SimCoach's AI settings, or a key you add here (it stays "
                       "on this PC).").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self.v["ai_colour"] = tk.BooleanVar(value=bool(cfg.get("ai_colour", True)))
        row(f, 1, "AI booth", ttk.Checkbutton(f, text="On", variable=self.v["ai_colour"]))
        row(f, 2, "Provider", combo(f, "ai_provider", list(PROVIDER_LABELS), PROVIDER_LABELS))
        has = cast.state()["settings"]["keys"]
        for i, (k, label) in enumerate((("openai_api_key", "OpenAI key"), ("gemini_api_key", "Gemini key"),
                                         ("deepseek_api_key", "DeepSeek key"))):
            row(f, 3 + i, label, entry(f, k, show="•"),
                ttk.Label(f, text="✓ set" if has.get(k) else "", style="Card.TLabel", foreground=P["green"]))
        st = cast.state()
        ttk.Label(f, style="Card.TLabel", foreground=P["green"] if st["ai"] else P["mut"],
                  text=f"Now using: {st['ai']}" if st["ai"] else "No AI key yet: the built-in booth is on its own."
                  ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))

        b = ttk.Frame(w, style="Card.TFrame", padding=(18, 0, 18, 16))
        b.pack(fill="x")
        ttk.Button(b, text="Save", style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(b, text="Cancel", command=w.destroy).pack(side="right", padx=8)
        w.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - w.winfo_reqwidth()) // 2
        y = app.root.winfo_rooty() + 70
        w.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _fill_voices(self, cfg):
        openai = cfg.get("tts") == "openai"
        for who, cb in self.voice_boxes.items():
            key = (f"openai_{who}_voice" if openai else f"{who}_voice")
            cur = cb.get() if getattr(cb, "_key", None) == key else (cfg.get(key) or DEFAULTS.get(key))
            cb.configure(values=OPENAI_VOICES if openai else EDGE_VOICES)
            cb.set(cur)
            cb._key = key
        self.vnote.configure(text="OpenAI voices speak every line with its own direction (calm, excited, "
                             "thrilled). They use your OpenAI key." if openai else
                             "Free Microsoft neural voices (needs the internet). Excitement comes through in pace, "
                             "pitch and volume.")

    def _collect(self):
        out = {}
        for k, var in self.v.items():
            if isinstance(var, tuple):
                txt, back = var[0].get(), var[1]
                out[k] = back.get(txt, txt)
            else:
                out[k] = var.get()
        for cb in self.voice_boxes.values():
            out[cb._key] = cb.get()
        try:
            out["demo_laps"] = int(out.get("demo_laps") or 8)
        except ValueError:
            out["demo_laps"] = 8
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

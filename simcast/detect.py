"""Which supported sims are installed on this PC, found without starting anything:

  Steam      every Steam library (Steam's registry entry, the default folders, libraryfolders.vdf), by app id
             (steamapps/appmanifest_<id>.acf) or install folder (steamapps/common/<folder>)
  iRacing    its own installer's folder
  EA app     F1 25 and EA SPORTS WRC also show up through their settings folders in Documents\\My Games

Each found sim gets a status line for the window: ready, or the one thing still to do.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

from .sims import _documents_dir


@dataclass
class Sim:
    key: str
    name: str
    appids: tuple = ()
    folders: tuple = ()                 # steamapps/common/<folder>, any case
    docs: tuple = ()                    # a settings folder under Documents that the game makes when first run
    other_paths: tuple = ()             # absolute paths outside Steam
    coverage: str = "field"             # field | own | rally
    found: bool = False
    where: str = ""
    status: str = ""
    ok: bool = True
    extra: dict = field(default_factory=dict)


def catalogue():
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    return [
        Sim("ac", "Assetto Corsa", (244210,), ("assettocorsa",)),
        Sim("acc", "Assetto Corsa Competizione", (805550,), ("Assetto Corsa Competizione",),
            docs=("Assetto Corsa Competizione",)),
        Sim("acevo", "Assetto Corsa EVO", (3058630,), ("Assetto Corsa EVO", "AssettoCorsaEVO"), coverage="own"),
        Sim("acr", "Assetto Corsa Rally", (), ("Assetto Corsa Rally", "AssettoCorsaRally"), coverage="rally"),
        Sim("lmu", "Le Mans Ultimate", (2399420,), ("Le Mans Ultimate",)),
        Sim("rf2", "rFactor 2", (365960,), ("rFactor 2",)),
        Sim("ams2", "Automobilista 2", (1066890,), ("Automobilista 2",)),
        Sim("r3e", "RaceRoom", (211500,), ("raceroom racing experience",)),
        Sim("iracing", "iRacing", (266410,), ("iRacing",), docs=("iRacing",),
            other_paths=(os.path.join(pf86, "iRacing"), os.path.join(pf, "iRacing"))),
        Sim("f1", "F1 25", (3059520,), ("F1 25", "F125"), docs=(os.path.join("My Games", "F1 25"),)),
        Sim("wrc", "EA SPORTS WRC", (1849250,), ("EA SPORTS WRC", "WRC"), docs=(os.path.join("My Games", "WRC"),),
            coverage="rally"),
        Sim("dr2", "DiRT Rally 2.0", (690790,), ("DiRT Rally 2.0",), docs=(os.path.join("My Games", "DiRT Rally 2.0"),),
            coverage="rally"),
    ]


def _steam_roots():
    roots = []
    if sys.platform == "win32":
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for name in ("SteamPath", "InstallPath"):
                            try:
                                roots.append(winreg.QueryValueEx(k, name)[0])
                            except OSError:
                                pass
                except OSError:
                    pass
        except Exception:
            pass
    roots += [os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Steam"),
              os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Steam")]
    return roots


_VDF_PATH = re.compile(r'"path"\s+"([^"]+)"')


def steam_libraries(roots=None):
    """Every Steam library folder (the ones that have a steamapps folder)."""
    libs, seen = [], set()
    for r in roots or _steam_roots():
        r = os.path.normpath(r.replace("/", os.sep)) if r else ""
        if not r or not os.path.isdir(os.path.join(r, "steamapps")):
            continue
        cands = [r]
        try:
            with open(os.path.join(r, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="ignore") as fh:
                cands += [p.replace("\\\\", "\\") for p in _VDF_PATH.findall(fh.read())]
        except OSError:
            pass
        for c in cands:
            c = os.path.normpath(c)
            if c.lower() not in seen and os.path.isdir(os.path.join(c, "steamapps")):
                seen.add(c.lower())
                libs.append(c)
    return libs


def scan(libraries=None, documents=None):
    """The catalogue with found / where / status filled in."""
    libs = steam_libraries() if libraries is None else libraries
    docs = documents or _documents_dir()
    sims = catalogue()
    commons = {}
    for lib in libs:
        common = os.path.join(lib, "steamapps", "common")
        try:
            commons[lib] = {d.lower(): os.path.join(common, d) for d in os.listdir(common)}
        except OSError:
            commons[lib] = {}
    for s in sims:
        for lib in libs:
            if any(os.path.isfile(os.path.join(lib, "steamapps", f"appmanifest_{a}.acf")) for a in s.appids):
                s.found, s.where = True, "Steam"
                s.extra["dir"] = next((commons[lib][f.lower()] for f in s.folders if f.lower() in commons[lib]), "")
                break
            hit = next((commons[lib][f.lower()] for f in s.folders if f.lower() in commons[lib]), None)
            if hit:
                s.found, s.where, s.extra["dir"] = True, "Steam", hit
                break
        if not s.found:
            p = next((p for p in s.other_paths if os.path.isdir(p)), None)
            if p:
                s.found, s.where, s.extra["dir"] = True, "installed", p
        if not s.found:
            d = next((os.path.join(docs, x) for x in s.docs if os.path.isdir(os.path.join(docs, x))), None)
            if d:
                s.found, s.where = True, "installed"
        if s.found:
            s.status, s.ok = _status(s, docs)
    return sims


def _status(s, docs):
    """(what to tell the player, ready?) for an installed sim."""
    from . import acc_broadcast, gamesetup
    if s.key == "ac":
        d = s.extra.get("dir", "")
        if d and not os.path.isdir(os.path.join(d, "apps", "python", "CrewChiefEx")):
            return "Your car only. For the whole grid, install CrewChief (it adds the CrewChiefEx app).", False
        if not gamesetup.crewchiefex_active(docs):
            return "Switch on the CrewChiefEx app in Content Manager (Settings > Python apps) for the whole grid.", False
        return "Ready: whole field (CrewChiefEx app on)", True
    if s.key == "acc":
        port, _ = acc_broadcast.read_config(docs)
        return ("Ready: whole field (broadcasting on)", True) if port > 0 else \
            ("SimCast switches on ACC's broadcasting port at start; restart ACC once after.", False)
    if s.key == "ams2":
        return "Set Options > System > Shared Memory to \"Project CARS 2\" once in the game.", True
    if s.key == "f1":
        on = gamesetup.f1_udp_on(docs)
        if on is None:
            return "Ready once the game has been started once (SimCast then switches on its UDP telemetry).", True
        return ("Ready: UDP telemetry on", True) if on else \
            ("SimCast switches on UDP telemetry at start; restart the game once after.", False)
    if s.key == "wrc":
        return ("Ready: rally stages", True) if gamesetup.ea_wrc_on(docs) else \
            ("SimCast adds its telemetry at start; restart the game once after.", False)
    if s.key == "dr2":
        return ("Ready: rally stages", True) if gamesetup.dr2_on(docs) else \
            ("SimCast switches on UDP telemetry at start; restart the game once after.", False)
    if s.coverage == "own":
        return "Ready: your car (AC EVO doesn't share the other cars)", True
    if s.coverage == "rally":
        return "Ready: rally stages", True
    return "Ready: whole field", True


def summary(sims):
    found = [s for s in sims if s.found]
    if not found:
        return "No supported sims found on this PC yet (SimCast still goes live when one starts)."
    return f"Found {len(found)}: " + ", ".join(s.name for s in found)

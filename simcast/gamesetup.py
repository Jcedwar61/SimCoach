"""One-time game settings SimCast makes for you, so the sims send it their data without you editing files.

  EA SPORTS WRC     a telemetry packet for SimCast (Documents\\My Games\\WRC\\telemetry: udp\\simcast.json and an
                    entry in config.json sending it to 127.0.0.1:20790)
  DiRT Rally 2.0    UDP telemetry on, with the extra data (Documents\\My Games\\DiRT Rally 2.0\\hardwaresettings\\
                    hardware_settings_config.xml: <udp enabled="true" extradata="3" port="20777" ...>)
  ACC               the broadcasting port (Documents\\Assetto Corsa Competizione\\Config\\broadcasting.json)

Each file is only touched when the setting is missing or off, and the original is kept next to it as
*.simcast-backup. A game reads these when it starts, so a game that's running needs a restart afterwards.
"""
from __future__ import annotations

import json
import os
import re

from . import acc_broadcast
from .sims import WRC_CHANNELS, WRC_PORT, _documents_dir

WRC_STRUCTURE = "simcast"


def _backup(path):
    try:
        if os.path.exists(path) and not os.path.exists(path + ".simcast-backup"):
            with open(path, "rb") as a, open(path + ".simcast-backup", "wb") as b:
                b.write(a.read())
    except Exception:
        pass


def setup_ea_wrc(documents, log=print):
    base = os.path.join(documents, "My Games", "WRC", "telemetry")
    cfg_path = os.path.join(base, "config.json")
    if not os.path.isfile(cfg_path):
        return False
    try:
        with open(cfg_path, encoding="utf-8-sig") as fh:
            cfg = json.load(fh)
    except Exception as e:
        log(f"EA WRC: couldn't read its telemetry settings ({e})")
        return False
    packets = cfg.setdefault("udp", {}).setdefault("packets", [])
    if any(p.get("port") == WRC_PORT and p.get("bEnabled") for p in packets if isinstance(p, dict)):
        return False                                         # already sending on SimCast's port
    udp_dir = os.path.join(base, "udp")
    versions = {"schema": 1, "data": 3}
    try:                                                     # match the format version of the game's own file
        with open(os.path.join(udp_dir, "wrc.json"), encoding="utf-8-sig") as fh:
            versions = json.load(fh).get("versions") or versions
    except Exception:
        pass
    structure = {"versions": versions, "id": WRC_STRUCTURE,
                 "packets": [{"id": "session_update", "channels": [name for name, _ in WRC_CHANNELS]}]}
    try:
        os.makedirs(udp_dir, exist_ok=True)
        with open(os.path.join(udp_dir, f"{WRC_STRUCTURE}.json"), "w", encoding="utf-8") as fh:
            json.dump(structure, fh, indent=2)
        _backup(cfg_path)
        packets[:] = [p for p in packets if not (isinstance(p, dict) and p.get("structure") == WRC_STRUCTURE)]
        packets.append({"structure": WRC_STRUCTURE, "packet": "session_update", "ip": "127.0.0.1",
                        "port": WRC_PORT, "frequencyHz": 60, "bEnabled": True})
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        log("EA WRC: telemetry for SimCast switched on (port 20790). Restart EA WRC if it's running.")
        return True
    except Exception as e:
        log(f"EA WRC: couldn't switch on telemetry ({e})")
        return False


_DR2_UDP = re.compile(r"<udp\b[^>]*/>")


def setup_dirt_rally_2(documents, log=print):
    path = os.path.join(documents, "My Games", "DiRT Rally 2.0", "hardwaresettings", "hardware_settings_config.xml")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            xml = fh.read()
    except Exception as e:
        log(f"DiRT Rally 2.0: couldn't read its settings ({e})")
        return False
    m = _DR2_UDP.search(xml)
    if m is None:
        return False
    tag = m.group(0)
    if re.search(r'enabled="true"', tag) and re.search(r'extradata="3"', tag):
        return False

    def attr(t, k, v):
        return re.sub(rf'{k}="[^"]*"', f'{k}="{v}"', t) if re.search(rf'\b{k}="', t) else t.replace("/>", f' {k}="{v}" />')
    new = attr(attr(tag, "enabled", "true"), "extradata", "3")
    if 'port="' not in new:
        new = attr(new, "port", "20777")
    try:
        _backup(path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(xml.replace(tag, new, 1))
        log("DiRT Rally 2.0: UDP telemetry switched on. Restart the game if it's running.")
        return True
    except Exception as e:
        log(f"DiRT Rally 2.0: couldn't switch on telemetry ({e})")
        return False


def setup_all(log=print, documents=None):
    """Every game SimCast can set up; returns the names it changed."""
    documents = documents or _documents_dir()
    done = []
    for name, fn in (("EA WRC", setup_ea_wrc), ("DiRT Rally 2.0", setup_dirt_rally_2),
                     ("ACC", lambda d, log: acc_broadcast.ensure_config(d, log=log))):
        try:
            if fn(documents, log=log):
                done.append(name)
        except Exception as e:
            log(f"{name}: setup skipped ({e})")
    return done

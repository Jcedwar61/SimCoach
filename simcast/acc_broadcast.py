"""ACC's broadcasting API: the whole grid for Assetto Corsa Competizione.

ACC's shared memory only has other cars' positions in space, not who they are or where they are in the race.
Its broadcasting interface (UDP, the one TV-style tools use) has everything: every car's driver, position,
laps, lap times, pit lane, plus the game's own events (accidents, penalties, best laps). SimCast connects as a
read-only broadcasting client on this PC.

The port and password come from Documents\\Assetto Corsa Competizione\\Config\\broadcasting.json (ACC writes it
in UTF-16; usually port 9000, password "asd"). Protocol version 4, as in Kunos' ksBroadcastingNetwork SDK.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time

PROTOCOL = 4
REGISTER, UNREGISTER, REQUEST_ENTRY_LIST, REQUEST_TRACK_DATA = 1, 9, 10, 11
IN_REGISTRATION, IN_REALTIME, IN_CAR, IN_ENTRY_LIST, IN_TRACK, IN_ENTRY_CAR, IN_EVENT = 1, 2, 3, 4, 5, 6, 7
CAR_LOCATION_PIT = (2, 3, 4)            # pit lane, pit entry, pit exit
SESSION = {0: "practice", 4: "qualifying", 9: "qualifying", 10: "race", 11: "practice", 12: "practice",
           13: "qualifying"}
EVENT = {1: "green", 2: "session_over", 3: "penalty", 4: "accident", 5: "lap", 6: "best_session_lap",
         7: "best_personal_lap"}


def config_path(documents):
    return os.path.join(documents, "Assetto Corsa Competizione", "Config", "broadcasting.json")


def read_config(documents):
    """(port, password) from ACC's broadcasting.json, or (9000, 'asd') when it can't be read."""
    try:
        raw = open(config_path(documents), "rb").read()
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in raw[:8] else raw.decode("utf-8")
        d = json.loads(text.strip("﻿"))
        return int(d.get("updListenerPort") or 0), str(d.get("connectionPassword") or "")
    except Exception:
        return 9000, "asd"


def ensure_config(documents, log=print):
    """Turn the broadcasting port on if it's off (0). ACC reads it at start, so it needs a restart after this."""
    path = config_path(documents)
    port, pw = read_config(documents)
    if port > 0 or not os.path.isdir(os.path.dirname(path)):
        return False
    try:
        if os.path.exists(path):
            os.replace(path, path + ".simcast-backup")
        d = {"updListenerPort": 9000, "connectionPassword": pw or "asd", "commandPassword": ""}
        with open(path, "wb") as fh:
            fh.write(json.dumps(d, indent=2).encode("utf-16"))
        log("ACC: switched on its broadcasting port (9000). Restart ACC once so it picks it up.")
        return True
    except Exception as e:
        log(f"ACC: couldn't switch on broadcasting ({e})")
        return False


class _Buf:
    def __init__(self, data):
        self.d, self.o = data, 0

    def take(self, fmt):
        v = struct.unpack_from("<" + fmt, self.d, self.o)
        self.o += struct.calcsize("<" + fmt)
        return v if len(v) > 1 else v[0]

    def string(self):
        n = self.take("H")
        s = self.d[self.o:self.o + n].decode("utf-8", "replace")
        self.o += n
        return s

    def lap(self):
        ms, car, drv, nsplits = self.take("iHHB")
        splits = [self.take("i") for _ in range(nsplits)]
        invalid, valid_best, outlap, inlap = self.take("BBBB")
        return {"ms": ms, "car": car, "splits": splits, "invalid": bool(invalid), "outlap": bool(outlap),
                "inlap": bool(inlap)}


def _s(text):
    b = text.encode("utf-8")
    return struct.pack("<H", len(b)) + b


class ACCBroadcast:
    """A background UDP client. field() gives the grid in SimCast's format; events() drains ACC's own events."""

    def __init__(self, documents, log=print, host="127.0.0.1", port=None, password=None, update_ms=250):
        cp, cpw = read_config(documents)
        self.addr = (host, port or cp or 9000)
        self.password = password if password is not None else cpw
        self.update_ms = update_ms
        self.log = log
        self.sock = None
        self.conn_id = None
        self.connected_at = None
        self.last_rx = 0.0
        self.cars: dict = {}           # car index -> entry dict
        self.state: dict = {}          # car index -> realtime dict
        self.session = {}
        self.track = {}
        self._events = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.error = ""

    # ------------------------------------------------------------------ connection
    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True, name="acc-broadcast")
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self.sock is not None and self.conn_id is not None:
            try:
                self.sock.sendto(struct.pack("<Bi", UNREGISTER, self.conn_id), self.addr)
            except OSError:
                pass

    def live(self):
        return self.conn_id is not None and time.monotonic() - self.last_rx < 5.0

    def _register(self):
        msg = (struct.pack("<BB", REGISTER, PROTOCOL) + _s("SimCast") + _s(self.password) +
               struct.pack("<i", self.update_ms) + _s(""))
        self.sock.sendto(msg, self.addr)

    def _run(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("127.0.0.1", 0))
            self.sock.settimeout(0.5)
        except OSError as e:
            self.error = str(e)
            return
        next_reg = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if (self.conn_id is None or now - self.last_rx > 5.0) and now >= next_reg:
                self.conn_id = None
                next_reg = now + 3.0
                try:
                    self._register()
                except OSError as e:
                    self.error = str(e)
            try:
                data, _ = self.sock.recvfrom(65535)
            except (socket.timeout, ConnectionResetError, OSError):
                continue
            self.last_rx = time.monotonic()
            try:
                self.handle(data)
            except Exception as e:                      # a malformed packet never stops the client
                self.error = f"{type(e).__name__}: {e}"

    def _request(self, kind):
        if self.conn_id is not None:
            try:
                self.sock.sendto(struct.pack("<Bi", kind, self.conn_id), self.addr)
            except OSError:
                pass

    # ------------------------------------------------------------------ messages
    def handle(self, data):
        b = _Buf(data)
        kind = b.take("B")
        if kind == IN_REGISTRATION:
            cid, ok, _ro = b.take("iBB")
            err = b.string()
            if ok:
                self.conn_id, self.connected_at = cid, time.monotonic()
                self.log("ACC: connected to the broadcasting API")
                self._request(REQUEST_ENTRY_LIST)
                self._request(REQUEST_TRACK_DATA)
            else:
                self.error = err or "ACC refused the connection (check the password in broadcasting.json)"
        elif kind == IN_REALTIME:
            _ev, _ses, stype, phase, stime, send, focused = b.take("HHBBffi")
            b.string(), b.string(), b.string()
            replay = b.take("B")
            if replay:
                b.take("ff")
            _tod, _air, _trk, _clouds, rain, wet = b.take("fBBBBB")
            best = b.lap()
            with self._lock:
                self.session = {"type": SESSION.get(stype, "practice"), "phase": phase, "time": stime / 1000.0,
                                "end": send / 1000.0, "focused": focused, "rain": rain / 10.0,
                                "best_ms": best["ms"] if best["ms"] > 0 and best["ms"] < 2 ** 31 - 1 else None}
        elif kind == IN_CAR:
            idx, _drv, _ndrv, _gear, _x, _y, _yaw, loc, kmh, pos, _cup, _tpos, spline, laps, _delta = \
                b.take("HHBBfffBHHHHfHi")
            best, last, _ = b.lap(), b.lap(), b.lap()
            with self._lock:
                self.state[idx] = {"loc": loc, "kmh": kmh, "pos": pos, "spline": spline, "laps": laps,
                                   "best": best["ms"], "last": last["ms"], "t": time.monotonic()}
                if idx not in self.cars:
                    self._request(REQUEST_ENTRY_LIST)
        elif kind == IN_ENTRY_LIST:
            _cid, n = b.take("iH")
            ids = [b.take("H") for _ in range(n)]
            with self._lock:
                for k in list(self.cars):
                    if k not in ids:
                        del self.cars[k]
        elif kind == IN_ENTRY_CAR:
            idx, model = b.take("HB")
            team = b.string()
            number, cup, cur_drv, nat, ndrv = b.take("iBBHB")
            drivers = []
            for _ in range(ndrv):
                first, last, short = b.string(), b.string(), b.string()
                cat, dnat = b.take("BH")
                drivers.append(f"{first} {last}".strip() or short)
            name = drivers[cur_drv] if 0 <= cur_drv < len(drivers) else (drivers[0] if drivers else f"Car {number}")
            with self._lock:
                self.cars[idx] = {"name": name, "number": number, "team": team, "model": model, "cup": cup}
        elif kind == IN_TRACK:
            b.take("i")                                   # connection id
            name = b.string()
            _tid, meters = b.take("ii")
            with self._lock:
                self.track = {"name": name, "meters": meters}
        elif kind == IN_EVENT:
            etype = b.take("B")
            msg = b.string()
            _ms, car = b.take("ii")
            with self._lock:
                self._events.append({"type": EVENT.get(etype, "other"), "msg": msg, "car": car})
                del self._events[:-40]

    # ------------------------------------------------------------------ for SimCast
    def field(self, field_entry, player_idx=None):
        """Every car as field_entry() dicts. player_idx: the car being driven (ACC's focused car by default)."""
        with self._lock:
            me = player_idx if player_idx is not None else self.session.get("focused")
            now = time.monotonic()
            out = []
            for idx, st in self.state.items():
                if now - st["t"] > 10.0:
                    continue
                e = self.cars.get(idx, {})
                ms = lambda x: x / 1000.0 if 0 < x < 2 ** 31 - 1 else None
                out.append(field_entry(idx, e.get("name") or f"Car {idx}", f"#{e.get('number', idx)}", st["pos"],
                                       st["laps"], st["spline"], st["loc"] in CAR_LOCATION_PIT, ms(st["last"]),
                                       ms(st["best"]), None, None, player=idx == me, speed=float(st["kmh"])))
            return out or None

    def events(self):
        """ACC's events in SimCast's sim_events format (accidents become contact, penalties penalties)."""
        with self._lock:
            evs, self._events = self._events, []
        out = []
        for e in evs:
            if e["type"] == "accident":
                out.append({"type": "accident", "car": e["car"]})
            elif e["type"] == "penalty":
                out.append({"type": "penalty", "car": e["car"], "seconds": 0, "msg": e["msg"]})
            elif e["type"] == "green":
                out.append({"type": "green_flag"})
        return out

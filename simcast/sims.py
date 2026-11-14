"""SimCast's sim readers: how SimCast reads every supported sim's live data (shared memory, the iRacing SDK,
UDP telemetry), including every car in the session (Frame.field) for the whole-field commentary.

Assetto Corsa, ACC, AC EVO, AC Rally, Le Mans Ultimate, rFactor 2, Automobilista 2, RaceRoom, iRacing, F1 25,
EA SPORTS WRC and DiRT Rally 2.0. Adapted from SimCoach's readers (same author, MIT licence); SimCast doesn't
need SimCoach to be installed.
"""
from __future__ import annotations

import json
import math
import os
import re
import struct
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
else:
    ctypes = None
    wintypes = None

LOOP_HZ = 60
RALLY_GAMES = {"EA WRC", "DiRT Rally 2.0", "AC Rally"}
_LOG = [print]


def file_log(msg, sync=False):
    """Where the readers' notes go (SimCast points this at its own log)."""
    try:
        _LOG[0](msg)
    except Exception:
        pass


def _documents_dir():
    """The real Documents folder (follows OneDrive / moved-folder redirection on Windows)."""
    if sys.platform == "win32" and ctypes is not None:
        try:
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return buf.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")



@dataclass(slots=True)
class Frame:
    game: str
    track: str
    car: str
    laps_done: int
    pct: float
    speed: float
    throttle: float
    brake: float
    steer: float
    gear: int
    rpm: float
    cur_time: float
    last_time: float
    in_pit: bool
    off_track: bool
    fuel: float = 0.0
    track_len: Optional[float] = None
    tyre_temps: Optional[list] = None
    max_rpm: float = 0.0
    wheel_kmh: Optional[list] = None
    tyre_press: Optional[list] = None
    restart: bool = False
    session: Optional[str] = None
    position: int = 0
    cars: int = 0
    race_laps: int = 0
    time_left: Optional[float] = None
    gap_ahead: Optional[float] = None
    gap_behind: Optional[float] = None
    fuel_cap: float = 0.0
    tyre_wear: Optional[list] = None
    damage: Optional[float] = None
    damage_parts: Optional[list] = None
    rain: Optional[float] = None
    pos: Optional[tuple] = None
    others: Optional[list] = None
    right: Optional[tuple] = None
    race_over: bool = False
    car_ahead: Optional[dict] = None
    car_behind: Optional[dict] = None
    others_meta: Optional[list] = None
    tyre_wear_frac: bool = False
    lap_invalid: bool = False
    flag: Optional[str] = None
    rain_in_10: Optional[float] = None
    rain_in_30: Optional[float] = None
    rain_later: Optional[float] = None
    precip: Optional[float] = None
    water_temp: Optional[float] = None
    oil_temp: Optional[float] = None
    energy: Optional[float] = None
    energy_lap: Optional[float] = None
    track_limits: Optional[int] = None
    field: Optional[list] = None          # every car in the session: see field_entry()
    sim_events: Optional[list] = None     # race events the sim itself reports (F1: overtakes, fastest lap, ...)


def field_entry(cid, name, car, position, laps, pct, in_pit=False, last=None, best=None, status=None, pits=None,
                player=False, speed=None, cls=None):
    """One car of Frame.field, the whole grid, for SimCast's commentary. Times in seconds (None when the sim doesn't
    say or the value isn't believable), pct is the fraction of the current lap, laps the laps completed, status one of
    None/'running', 'finished', 'dnf', 'dsq'. Kept small and plain so a capture or a test can build one by hand."""
    def t(x):
        return float(x) if x is not None and 10.0 < x < 3600.0 else None
    return {"id": cid, "name": (name or "").strip() or f"Car {cid}", "car": car or "", "cls": cls or "",
            "position": max(0, int(position or 0)), "laps": max(0, int(laps or 0)),
            "pct": float(pct) % 1.0 if pct is not None and pct == pct else 0.0, "in_pit": bool(in_pit),
            "last": t(last), "best": t(best), "status": status, "pits": pits, "player": bool(player),
            "speed": float(speed) if speed is not None and 0.0 <= speed < 600.0 else None}


class Reader:
    name = "?"
    CAP_BLOCKS = ()

    def connected(self) -> bool:
        raise NotImplementedError

    def raw_blocks(self):
        """{name: block} for every shared-memory block this reader has open (for a capture)."""
        out = {}
        for name, attr, idx in self.CAP_BLOCKS:
            x = getattr(self, attr, None)
            if x is not None and idx is not None:
                x = x[idx] if idx < len(x) else None
            if x is not None:
                out[name] = x
        return out

    def load_raw_blocks(self, blocks):
        """The other way round, for replaying a capture: put recorded bytes where the live blocks would be."""
        for name, attr, idx in self.CAP_BLOCKS:
            data = blocks.get(name)
            blk = _RawBlock(data) if data is not None else None
            if idx is None:
                setattr(self, attr, blk)
            else:
                cur = list(getattr(self, attr, None) or [])
                cur += [None] * (idx + 1 - len(cur))
                cur[idx] = blk
                setattr(self, attr, cur)

    def read(self) -> Optional[Frame]:
        raise NotImplementedError

    def close(self) -> None:
        pass


def _wstr(buf, off: int, nchars: int) -> str:
    return bytes(buf[off:off + nchars * 2]).decode("utf-16-le", "ignore").split("\x00")[0].strip()


_U_f = struct.Struct("<f").unpack_from
_U_d = struct.Struct("<d").unpack_from
_U_i = struct.Struct("<i").unpack_from
_U_I = struct.Struct("<I").unpack_from
_U_H = struct.Struct("<H").unpack_from
_U_h = struct.Struct("<h").unpack_from
_U_b = struct.Struct("<b").unpack_from
_U_2i = struct.Struct("<2i").unpack_from
_U_2f = struct.Struct("<2f").unpack_from
_U_3f = struct.Struct("<3f").unpack_from
_U_4f = struct.Struct("<4f").unpack_from
_U_5f = struct.Struct("<5f").unpack_from
_U_4i = struct.Struct("<4i").unpack_from
_U_3d = struct.Struct("<3d").unpack_from
_U_3h = struct.Struct("<3h").unpack_from
_U_II = struct.Struct("<II").unpack_from
_U_Hfff = struct.Struct("<Hfff").unpack_from
_U_F1_HDR = struct.Struct("<HBBBBB").unpack_from
_ZERO8 = bytes(8)
_U_DR2 = struct.Struct("<66f").unpack_from


class ACReader(Reader):
    """Assetto Corsa, ACC and AC Rally share the acpmf_* shared-memory layout for every field used here."""
    CAP_BLOCKS = (("physics", "m", 0), ("graphics", "m", 1), ("static", "m", 2), ("crewchief", "ccx", None),
                  ("cspweather", "cspw", None))
    name = "AC / ACC / AC Rally"
    GAMES = (("acs.exe", "AC"), ("acs_x86", "AC"), ("ac2-win64", "ACC"), ("acr.exe", "AC Rally"), ("acr-win64", "AC Rally"))

    def __init__(self):
        self.m = None
        self._cur_game = None
        self._proc_snap = None
        self.ccx, self._ccx_retry = None, 0.0
        self.cspw, self._cspw_retry = None, 0.0
        self._cspw_seq, self._cspw_seen, self._cspw_seg, self._cspw_hist = None, 0.0, None, deque(maxlen=240)
        self._cspw_ok = False
        self._chk_lap = None
        self._laps_seen, self._laps_changed = None, -99.0
        self._static = None
        self._acc_v = {}
        self._wcal = _WheelCal()
        self._pl_fast, self._pl_off = None, False
        self._vl_seen = False

    def _game(self):
        _PROCS.ensure()
        snap = _PROCS.state[0]
        if snap is self._proc_snap:
            return self._cur_game
        self._proc_snap = snap
        for exe, label in self.GAMES:
            if running(exe):
                self._cur_game = label
                return label
        self._cur_game = None
        return None

    def close(self):
        self._chk_lap, self._laps_seen, self._laps_changed = None, None, -99.0
        self._static = None
        self._acc_v = {}
        if self.m:
            for x in self.m:
                if x:
                    x.close()
            self.m = None
        if getattr(self, "ccx", None) is not None:
            self.ccx.close()
            self.ccx = None
        self._cspw_seq, self._cspw_seen, self._cspw_seg, self._cspw_ok = None, 0.0, None, False
        self._cspw_hist.clear()
        if getattr(self, "cspw", None) is not None:
            self.cspw.close()
            self.cspw = None

    def connected(self) -> bool:
        if self._game() is None:
            self.close()
            return False
        if self.m is None:
            parts = [SharedMem.open(f"Local\\acpmf_{n}") for n in ("physics", "graphics", "static")]
            if not all(parts):
                for x in parts:
                    if x:
                        x.close()
                return False
            self.m = parts
        return _i(self.m[1][0:12], 4) in (2, 3)

    def read(self) -> Optional[Frame]:
        p, g, s = self.m[0][0:800], self.m[1][0:1600], self.m[2][0:1200]
        if _i(g, 4) != 2:
            return None
        st = self._static
        if st is None or st[0] != s:
            self._chk_lap = self._laps_seen = None
            self._acc_v.clear()
            self._wcal.reset()
            self._pl_fast, self._pl_off, self._vl_seen = None, False, False
            radius = _U_4f(s, 436)
            st = self._static = (s, _wstr(s, 134, 33), _wstr(s, 68, 33), _f(s, 520), radius, _i(s, 412),
                                 all(0.15 < r < 0.6 for r in radius), max(0, _i(s, 64)), max(0.0, _f(s, 416)),
                                 _wstr(s, 524, 33).strip())
        _s, track, car_name, spline, radius, max_rpm, radius_ok, n_cars, max_fuel, layout = st
        if not track:
            return None
        game = self._cur_game or self._game() or "AC"
        if layout and game != "ACC" and layout.lower() not in track.lower():
            track = f"{track} ({layout})"
        gas, brake, fuel = _U_3f(p, 4)
        gear, rpm = _U_2i(p, 16)
        steer, speed = _U_2f(p, 24)
        temps = list(_U_4f(p, 152))
        temps = [t - 273.15 if t > 200 else t for t in temps]
        press = list(_U_4f(p, 88))
        omega = _U_4f(p, 104)
        wheel_kmh = ([abs(w) * r * 3.6 for w, r in zip(omega, radius)] if radius_ok
                     else self._wcal.update(speed, gas, brake, omega))
        tyres_out = _i(p, 244)
        laps_done, _pos, i_cur, i_last = _U_4i(g, 132)
        laps_done, _pos = max(0, laps_done), max(0, _pos)
        in_pit = _i(g, 160) != 0
        if game == "ACC" and not self._pl_off:
            pl = _i(g, 1236)
            if pl == 1 and speed > 130.0:
                t_m = time.monotonic()
                if self._pl_fast is None:
                    self._pl_fast = t_m
                elif t_m - self._pl_fast > 3.0:
                    self._pl_off = True
                in_pit = True
            elif pl in (0, 1):
                self._pl_fast = None
                in_pit = in_pit or pl == 1
        pct = _f(g, 248)
        fr = Frame(game, track, car_name, laps_done, max(0.0, min(0.99999, pct)),
                   speed, gas, brake, steer, gear - 1, float(rpm), i_cur / 1000.0, max(0, i_last) / 1000.0,
                   in_pit, tyres_out > 2, fuel, spline if 500 < spline < 40000 else None,
                   temps if any(t > 1 for t in temps) else None, float(max_rpm),
                   wheel_kmh, press if any(x > 5 for x in press) else None)
        if game != "AC Rally":
            fr.session = {0: "practice", 1: "qualifying", 2: "race", 3: "practice", 4: "practice", 7: "practice",
                          8: "qualifying"}.get(_i(g, 8))
            fr.position, fr.cars = _pos, n_cars
            laps = _i(g, 172)
            fr.race_laps = laps if 0 < laps < 1000 else 0
            tl = _f(g, 152) / 1000.0
            fr.time_left = tl if 0 < tl < 86400 and not fr.race_laps else None
            flag = _i(g, 1224 if game == "ACC" else 268)
            fr.flag = {1: "blue", 2: "yellow"}.get(flag)
            now_m = time.monotonic()
            if laps_done != self._laps_seen:
                if self._laps_seen is not None:
                    if laps_done > self._laps_seen:
                        self._laps_changed = now_m
                    else:
                        self._chk_lap = None
                self._laps_seen = laps_done
            if flag == 5 and fr.session == "race":
                if self._chk_lap is None:
                    took_it = now_m - self._laps_changed < (0.4 if _pos == 1 else 0.12)
                    self._chk_lap = laps_done - 1 if took_it else laps_done
            elif fr.session != "race" or laps_done == 0:
                self._chk_lap = None
            fr.race_over = bool(fr.session == "race" and (
                (self._chk_lap is not None and laps_done > self._chk_lap)
                or (fr.race_laps > 0 and laps_done >= fr.race_laps)))
            fr.fuel_cap = max_fuel
            fr.damage_parts = list(_U_5f(p, 224))
            if game == "ACC":
                self._acc_race(fr, g)
                w = _f(p, 712)
                fr.water_temp = w if 20.0 < w < 200.0 else None
                valid = _i(g, 1408)
                if valid == 1:
                    self._vl_seen = True
                elif valid == 0 and self._vl_seen:
                    fr.lap_invalid = True
                self._acc_cars(fr, g, speed)
                self._acc_field(fr, g)
            else:
                if game == "AC":
                    self._csp_weather(fr)
                self._crewchief(fr, _i(g, 148), i_last)
        return fr

    _CSP_RAIN = {0: 0.1, 1: 0.2, 2: 0.4, 3: 0.05, 4: 0.15, 5: 0.25, 6: 0.3, 7: 0.6, 8: 1.0, 12: 0.2, 13: 0.5, 14: 0.8,
                 27: 0.3, 28: 0.5, 32: 0.5}

    def _csp_weather(self, fr):
        """Original AC has no weather of its own: with Custom Shaders Patch it's whatever the WeatherFX runs (Pure and
        Pure Planner, Sol...). The SimCoach Weather Link app (apps/lua/SimCoachWeather, installed by SimCoach) shares
        it as Local\\SimCoach.CSPWeather.v1, 64 bytes, natural alignment: version @0, seq @4 (odd mid-write),
        currentType @8, upcomingType @12 (ac.WeatherType), transition @16, rainIntensity @20, rainWetness @24,
        rainWater @28, ambient @32, road temp @36, roadGrip @40, time multiplier @44, weatherFX @48, CSP build @52,
        time of day @56 (double). Rain and track: fr.rain; what's next (Pure Planner's next weather, timed from how
        fast the blend into it moves): rain_in_10 / rain_in_30, or rain_later when it hasn't started yet."""
        now = time.monotonic()
        w = self.cspw
        if w is None:
            if now < self._cspw_retry:
                return
            self._cspw_retry = now + 5.0
            w = self.cspw = SharedMem.open(CSP_WEATHER_MMF)
            if w is None:
                return
        raw = w[0:64]
        ver, seq, cur, nxt = _U_4i(raw, 0)
        if ver != 1 or seq & 1 or _i(w[0:8], 4) != seq:
            return
        if seq != self._cspw_seq:
            self._cspw_seq, self._cspw_seen = seq, now
        elif now - self._cspw_seen > 3.0:
            return
        trans, rain, wet, water = _U_4f(raw, 16)
        if not all(0.0 <= x <= 2.0 for x in (trans, rain, wet, water)):
            return
        if not self._cspw_ok:
            self._cspw_ok = True
            file_log(f"AC weather from CSP / Pure: connected (CSP build {_i(raw, 52)}, WeatherFX {'on' if _i(raw, 48) else 'off'})")
        track = max(water, 0.3 * wet)
        fr.rain = max(min(rain, 1.0), track if track >= 0.15 else 0.0)
        fr.precip = min(rain, 1.0)
        hist = self._cspw_hist
        if (cur, nxt) != self._cspw_seg or (hist and trans < hist[-1][1] - 0.05):
            self._cspw_seg = (cur, nxt)
            hist.clear()
        if not hist or now - hist[-1][0] >= 1.0:
            hist.append((now, trans))
        while hist and now - hist[0][0] > 60.0:
            hist.popleft()
        rate = None
        if len(hist) >= 2:
            k = 0
            while k + 1 < len(hist) and hist[k + 1][1] <= hist[0][1] + 1e-6:
                k += 1
            if hist[-1][0] - hist[k][0] >= 5.0 or (k == 0 and hist[-1][0] - hist[0][0] >= 10.0):
                rate = (hist[-1][1] - hist[k][1]) / (hist[-1][0] - hist[k][0])
        r_now, r_next = max(rain, self._CSP_RAIN.get(cur, 0.0)), self._CSP_RAIN.get(nxt, 0.0)
        soon = later = eventually = 0.0
        if r_next >= r_now + 0.05:
            onset = max(0.02, (0.05 - r_now) / (r_next - r_now))
            if trans >= onset:
                soon = later = r_next
            elif rate is not None and rate > 1e-5:
                eta = (onset - trans) / rate
                if eta <= 600:
                    soon = later = r_next
                elif eta <= 1800:
                    later = r_next
                else:
                    eventually = r_next
            else:
                eventually = r_next
        fr.rain_in_10, fr.rain_in_30, fr.rain_later = soon, later, eventually

    _ACC_RAIN = (0.0, 0.1, 0.3, 0.55, 0.8, 1.0)
    _ACC_GRIP_WET = (0.0, 0.0, 0.0, 0.0, 0.04, 0.45, 0.8)

    def _acc_race(self, fr, g):
        """ACC graphics page, after isValidLap (field order as in Kunos' SPageFileGraphic, pack 4): trackGripStatus
        @1556, rainIntensity @1560, rainIntensityIn10min @1564, rainIntensityIn30min @1568, gapAhead/gapBehind @1580/
        @1584 (milliseconds)."""
        grip, rain, r10, r30 = _U_4i(g, 1556)
        if 0 <= rain <= 5 and 0 <= grip <= 6:
            fr.rain = max(self._ACC_RAIN[rain], self._ACC_GRIP_WET[grip])
            fr.precip = self._ACC_RAIN[rain]
            if 0 <= r10 <= 5:
                fr.rain_in_10 = self._ACC_RAIN[r10]
            if 0 <= r30 <= 5:
                fr.rain_in_30 = self._ACC_RAIN[r30]
        ga, gb = _U_2i(g, 1580)
        if fr.position > 1 and 0 < ga < 600000:
            fr.gap_ahead = ga / 1000.0
        if fr.position >= 1 and 0 < gb < 600000:
            fr.gap_behind = gb / 1000.0

    def _acc_cars(self, fr, g, speed):
        """ACC's graphics page holds every car's world position (no app needed): activeCars @252,
        carCoordinates[60][3] @256, carID[60] @976, playerCarID @1216. Each car's speed comes from how far it moved,
        so a car crawling down the pit lane beside the straight, or parked off the track, isn't called alongside."""
        n = _i(g, 252)
        if not 0 < n <= 60:
            return
        ids = struct.unpack_from(f"<{n}i", g, 976)
        try:
            k_me = ids.index(_i(g, 1216))
        except ValueError:
            return
        xyz = struct.unpack_from(f"<{3 * n}f", g, 256)
        mx, my, mz = fr.pos = xyz[3 * k_me:3 * k_me + 3]
        now = time.monotonic()
        vel = self._acc_v
        floor = 0.6 * speed
        others = []
        for k in range(n):
            if k == k_me:
                continue
            o = 3 * k
            x, y, z = xyz[o:o + 3]
            cid = ids[k]
            prev = vel.get(cid)
            if prev is None or now - prev[0] > 1.0:
                prev = vel[cid] = (now, x, z, None)
            elif now - prev[0] >= 0.2:
                prev = vel[cid] = (now, x, z, math.hypot(x - prev[1], z - prev[2]) / (now - prev[0]) * 3.6)
            if abs(x - mx) <= 10.0 and abs(z - mz) <= 10.0 and (prev[3] is None or prev[3] >= floor):
                others.append((x, y, z))
        fr.others = others

    def _acc_field(self, fr, g):
        """The whole grid from ACC's broadcasting API (simcast/acc_broadcast.py), started on the first ACC frame."""
        bc = getattr(self, "_acc_bc", None)
        if bc is None:
            from .acc_broadcast import ACCBroadcast, ensure_config
            ensure_config(_documents_dir(), log=file_log)
            bc = self._acc_bc = ACCBroadcast(_documents_dir(), log=file_log)
            bc.start()
        if bc.live():
            me = _i(g, 1216)
            fr.field = bc.field(field_entry, player_idx=me if 0 <= me < 1000 else None)
            evs = bc.events()
            if evs:
                fr.sim_events = evs
            if bc.session.get("type"):
                fr.session = bc.session["type"]

    def _crewchief(self, fr, best_ms, last_ms):
        """Other cars come from the CrewChiefEx AC app (apps/python/CrewChiefEx, on in Content Manager > Settings >
        Assetto Corsa > Python apps): it shares every car's position 40 times a second as 'acpmf_crewchief'.
        Layout from its shared_mem.py (pack 4): numVehicles @0, focusVehicle @4, vehicleInfo[128] @520, 228 bytes
        each: driverName @4 (64B), carModel @68 (64B), lapCount @140, worldPosition @156, isCarInPit @172,
        realtime position (0-based) @180, spline position @184, isConnected @188."""
        now = time.monotonic()
        if self.ccx is None:
            if now < self._ccx_retry:
                return
            self._ccx_retry = now + 5.0
            self.ccx = SharedMem.open("Local\\acpmf_crewchief")
            if self.ccx is None:
                return
        n, me = _U_2i(self.ccx[0:8], 0)
        if not 0 < n <= 128 or not 0 <= me < n:
            return
        blk = self.ccx[520:520 + n * 228]
        cars = []
        for k in range(n):
            o = k * 228
            if not _i(blk, o + 188):
                continue
            cars.append((k, _U_3f(blk, o + 156), _i(blk, o + 140) + _f(blk, o + 184),
                         _i(blk, o + 180), _i(blk, o + 172), o))
        mine = next((c for c in cars if c[0] == me), None)
        if mine is None:
            return
        mx, _my, mz = fr.pos = mine[1]
        # Whole grid (speedMS @132, bestLapMS @136, lastLapMS @152, isCarInPitline @168).
        fr.field = [field_entry(c[0], _cstr(blk, c[5] + 4, 64), nice_name(_cstr(blk, c[5] + 68, 64)), c[3] + 1,
                                _i(blk, c[5] + 140), _f(blk, c[5] + 184), bool(c[4] or _i(blk, c[5] + 168)),
                                _i(blk, c[5] + 152) / 1000.0, _i(blk, c[5] + 136) / 1000.0, player=c[0] == me,
                                speed=_f(blk, c[5] + 132) * 3.6)
                    for c in cars if c[3] >= 0]
        others_pos, others_meta = [], []
        for c in cars:
            if c[0] != me and not c[4]:
                cp = c[1]
                ddx, ddz = abs(cp[0] - mx), abs(cp[2] - mz)
                if ddx <= 10.0 and ddz <= 10.0:
                    others_pos.append(cp)
                if ddx <= 25.0 and ddz <= 25.0:
                    co = c[5]
                    others_meta.append({"pos": cp, "name": _cstr(blk, co + 4, 64), "position": c[3] + 1 if c[3] >= 0 else 0,
                                        "car": nice_name(_cstr(blk, co + 68, 64))})
        fr.others = others_pos
        if others_meta:
            fr.others_meta = others_meta
        tlen = fr.track_len or 4000.0
        lap_s = (best_ms if best_ms > 0 else last_ms) / 1000.0
        ahead = next((c for c in cars if c[3] == mine[3] - 1), None) if mine[3] > 0 else None
        behind = next((c for c in cars if c[3] == mine[3] + 1), None) if mine[3] >= 0 else None
        if ahead is not None:
            ao = ahead[5]
            dpct = ahead[2] - mine[2]
            dist_m = dpct * tlen if 0 < dpct < 1 else math.hypot(ahead[1][0] - mx, ahead[1][2] - mz)
            if lap_s > 10 and 0 < dpct < 1:
                fr.gap_ahead = dpct * lap_s
            fr.car_ahead = {"name": _cstr(blk, ao + 4, 64), "position": ahead[3] + 1,
                            "car": nice_name(_cstr(blk, ao + 68, 64)),
                            "distance_m": round(max(1.0, dist_m)), "gap_s": fr.gap_ahead}
        if behind is not None:
            bo = behind[5]
            dpct = mine[2] - behind[2]
            dist_m = dpct * tlen if 0 < dpct < 1 else math.hypot(behind[1][0] - mx, behind[1][2] - mz)
            if lap_s > 10 and 0 < dpct < 1:
                fr.gap_behind = dpct * lap_s
            fr.car_behind = {"name": _cstr(blk, bo + 4, 64), "position": behind[3] + 1,
                             "car": nice_name(_cstr(blk, bo + 68, 64)),
                             "distance_m": round(max(1.0, dist_m)), "gap_s": fr.gap_behind}



def _cstr(buf, off, n):
    return bytes(buf[off:off + n]).split(b"\x00")[0].decode("utf-8", "ignore").strip()


class SharedMem:
    """Read-only view of a game's named shared-memory block. Opens existing blocks only (never creates
    them) and maps the whole block, so it works whatever size the game made it."""

    def __init__(self, ptr, size, handle, k32):
        self.ptr, self.size, self.handle, self.k32 = ptr, size, handle, k32
        try:
            self.view = memoryview((ctypes.c_ubyte * size).from_address(ptr)).cast("B")
        except Exception:
            self.view = None

    _k32 = None
    _MBI = None

    @classmethod
    def open(cls, name):
        if sys.platform != "win32" or ctypes is None:
            return None
        if cls._k32 is None:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenFileMappingW.restype = wintypes.HANDLE
            k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
            k32.MapViewOfFile.restype = ctypes.c_void_p
            k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
            k32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
            k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]

            class MBI(ctypes.Structure):
                _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                            ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
                            ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                            ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]
            cls._k32, cls._MBI = k32, MBI
        k32 = cls._k32
        h = k32.OpenFileMappingW(0x0004, False, name)
        if not h:
            return None
        p = k32.MapViewOfFile(h, 0x0004, 0, 0, 0)
        if not p:
            k32.CloseHandle(h)
            return None
        mbi = cls._MBI()
        k32.VirtualQuery(p, ctypes.byref(mbi), ctypes.sizeof(mbi))
        return cls(p, int(mbi.RegionSize), h, k32)

    def __getitem__(self, key):
        if isinstance(key, slice):
            a = key.start or 0
            b = self.size if key.stop is None else key.stop
            n = max(0, min(b, self.size) - a)
            data = ctypes.string_at(self.ptr + a, n) if n else b""
            return data if len(data) == b - a else data + bytes(max(0, (b - a) - len(data)))
        if 0 <= key < self.size:
            return ctypes.string_at(self.ptr + key, 1)[0]
        return 0

    def close(self):
        self.view = None
        try:
            self.k32.UnmapViewOfFile(self.ptr)
            self.k32.CloseHandle(self.handle)
        except Exception:
            pass


class _RawBlock:
    """Recorded bytes standing in for a SharedMem block (replaying a capture): same slicing rules."""

    def __init__(self, data):
        self.data = bytes(data)
        self.size = len(self.data)
        self.view = memoryview(self.data)

    def __getitem__(self, key):
        if isinstance(key, slice):
            a = key.start or 0
            b = self.size if key.stop is None else key.stop
            d = self.data[a:b]
            return d if len(d) == b - a else d + bytes(max(0, (b - a) - len(d)))
        return self.data[key] if 0 <= key < self.size else 0

    def __len__(self):
        return self.size

    def close(self):
        pass


def _span(m, a, n):
    """m[a:a+n] without a copy when the mapping covers it: a live view for arrays of other cars, read once and
    dropped within the same read() (the player's own records are still snapshot copies). Plain bytes (tests)
    give a zero-copy view too; a short block falls back to the zero-padded copy."""
    v = getattr(m, "view", None)
    if v is None and isinstance(m, (bytes, bytearray)):
        v = memoryview(m)
    if v is not None and a + n <= len(v):
        return v[a:a + n]
    return memoryview(m[a:a + n])



CSP_WEATHER_MMF = "Local\\SimCoach.CSPWeather.v1"   # read if SimCoach's CSP weather app is running
class _ProcScanner:
    """Keeps the list of running .exe names fresh in the background so the telemetry loop never stalls."""

    def __init__(self):
        self.state = (frozenset(), {})
        self._started = False
        self._lock = threading.Lock()

    @property
    def names(self):
        return self.state[0]

    def _scan(self):
        try:
            import psutil
            new_names = frozenset((p.info["name"] or "").lower() for p in psutil.process_iter(["name"]))
            if new_names != self.state[0]:
                self.state = (new_names, {})
        except Exception:
            pass

    def ensure(self):
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            self._started = True
        self._scan()

        def loop():
            while True:
                time.sleep(2)
                self._scan()
        threading.Thread(target=loop, daemon=True, name="proc-scan").start()


_PROCS = _ProcScanner()


def running(*names):
    """True if a running process's exe name contains any of `names`."""
    _PROCS.ensure()
    current, cache = _PROCS.state
    hit = cache.get(names)
    if hit is not None:
        return hit
    res = any(n.lower() in pn for n in names for pn in current)
    cache[names] = res
    return res


def _f(b, o, _u=_U_f):
    return _u(b, o)[0]


def _d(b, o, _u=_U_d):
    return _u(b, o)[0]


def _i(b, o, _u=_U_i):
    return _u(b, o)[0]


class _WheelCal:
    """Wheel surface speeds for sims that publish how fast each wheel spins but no usable tyre radius (ACC leaves
    tyreRadius empty, AMS2 has none, encrypted rF2/LMU cars can send 0): each wheel's km/h-per-spin factor is learnt
    while the car rolls freely (60-300 km/h, off the brake, part throttle) as the median of speed / spin. Units cancel,
    so rad/s or rev/s both work. Until ~1 s of such driving has been seen there are no wheel speeds (no lock-up calls)."""
    N, MIN = 150, 60

    def __init__(self):
        self.reset()

    def reset(self):
        self.samples = ([], [], [], [])
        self.k = None
        self._n = 0

    def update(self, spd, thr, brk, spins):
        if 60.0 < spd < 300.0 and brk < 0.02 and thr < 0.6:
            for lst, w in zip(self.samples, spins):
                a = abs(w)
                if a > 1e-3:
                    lst.append(spd / a)
                    if len(lst) > self.N:
                        del lst[0]
            self._n += 1
            if self._n % 15 == 0 and all(len(lst) >= self.MIN for lst in self.samples):
                ks = [sorted(lst)[len(lst) // 2] for lst in self.samples]
                fr_ratio, rr_ratio = ks[0] / ks[1], ks[2] / ks[3]
                if 0.9 < fr_ratio < 1.1 and 0.9 < rr_ratio < 1.1:
                    self.k = ks
        k = self.k
        return [abs(w) * kk for w, kk in zip(spins, k)] if k else None



class ACEvoReader(Reader):
    name = "AC EVO"
    CAP_BLOCKS = (("physics", "m", 0), ("graphics", "m", 1), ("static", "m", 2))

    def __init__(self):
        self.m = None

    def close(self):
        if self.m:
            for x in self.m:
                if x:
                    x.close()
            self.m = None

    def _open(self):
        if self.m is None and running("assettocorsaevo"):
            parts = [
                SharedMem.open("Local\\acevo_pmf_physics"),
                SharedMem.open("Local\\acevo_pmf_graphics"),
                SharedMem.open("Local\\acevo_pmf_static"),
            ]
            if all(parts):
                self.m = tuple(parts)
            else:
                for x in parts:
                    if x:
                        x.close()
        return self.m

    def connected(self):
        if not running("assettocorsaevo"):
            self.close()
            return False
        return self._open() is not None

    def read(self):
        p, g, st = self.m[0][0:800], self.m[1][0:4900], self.m[2][0:208]
        if _i(g, 4) != 2 or not _cstr(st, 136, 33):
            return None
        tl = _f(st, 204)
        temps = list(_U_4f(p, 152))
        temps = [t - 273.15 if t > 200 else t for t in temps]
        press = list(_U_4f(p, 88))
        return Frame("AC EVO", _cstr(st, 136, 33), _cstr(g, 3086, 33), _i(g, 2384),
                     max(0.0, min(0.99999, _f(g, 1244))), _f(p, 28), _f(p, 4), _f(p, 8), _f(p, 24),
                     _i(p, 16) - 1, float(_i(p, 20)), _i(g, 188) / 1000.0, max(0, _i(g, 2396)) / 1000.0,
                     bool(g[3120]), False, _f(p, 12), tl if 500 < tl < 40000 else None,
                     temps if any(t > 1 for t in temps) else None, 0.0, None,
                     press if any(x > 5 for x in press) else None, lap_invalid=not bool(g[3121]))



class _RF2Family(Reader):
    """LMU and rFactor 2 share Studio 397's TelemInfoV01 / VehicleScoringInfoV01 records."""

    @staticmethod
    def _race_state(fr, sc_info, veh, tel, vehicles, telems):
        """ScoringInfoV01 / VehicleScoringInfoV01 / TelemInfoV01 fields (offsets from InternalsPlugin.hpp, pack 4).
        rF2 world space is left-handed with +y up."""
        ses = _i(sc_info, 64)
        fr.session = "practice" if 0 <= ses <= 4 or ses == 9 else "qualifying" if 5 <= ses <= 8 else \
            "race" if 10 <= ses <= 13 else None
        end_et, cur_et, max_laps = _d(sc_info, 76), _d(sc_info, 68), _i(sc_info, 84)
        fr.race_laps = max_laps if 0 < max_laps < 1000 else 0
        fr.time_left = end_et - cur_et if end_et > 0 and not fr.race_laps and end_et - cur_et > 0 else None
        my_plc = max(0, _U_b(veh, 199)[0])
        fr.position, fr.cars = my_plc, max(0, _i(sc_info, 104))
        finish_st = _U_b(veh, 103)[0]
        game_phase = sc_info[108]
        fr.race_over = bool(fr.session == "race" and (
            finish_st == 1 or game_phase == 8 or (fr.race_laps > 0 and fr.laps_done >= fr.race_laps)
        ))
        my_dist = _d(veh, 104)
        lap_len = fr.track_len or _d(sc_info, 88) or 4000.0
        if my_plc > 1 and _i(veh, 240) == 0:
            ga = _d(veh, 232)
            fr.gap_ahead = ga if 0 < ga < 600 else None
        ahead_v = behind_v = None
        for v in vehicles:
            plc = _U_b(v, 199)[0]
            if plc == my_plc - 1 and my_plc > 1:
                ahead_v = v
            elif plc == my_plc + 1 and my_plc >= 1:
                behind_v = v
                if _i(v, 240) == 0:
                    gb = _d(v, 232)
                    fr.gap_behind = gb if 0 < gb < 600 else None
        if ahead_v is not None:
            adist = (_d(ahead_v, 104) - my_dist) % lap_len if lap_len > 0 else 0.0
            if adist <= 0 and fr.gap_ahead:
                adist = fr.gap_ahead * max(fr.speed, 60.0) / 3.6
            fr.car_ahead = {"name": _cstr(ahead_v, 4, 32), "position": int(ahead_v[199]),
                            "car": nice_name(_cstr(ahead_v, 36, 64)),
                            "distance_m": round(max(1.0, adist)), "gap_s": fr.gap_ahead}
        if behind_v is not None:
            bdist = (my_dist - _d(behind_v, 104)) % lap_len if lap_len > 0 else 0.0
            if bdist <= 0 and fr.gap_behind:
                bdist = fr.gap_behind * max(fr.speed, 60.0) / 3.6
            fr.car_behind = {"name": _cstr(behind_v, 4, 32), "position": int(behind_v[199]),
                             "car": nice_name(_cstr(behind_v, 36, 64)),
                             "distance_m": round(max(1.0, bdist)), "gap_s": fr.gap_behind}
        fr.fuel_cap = _d(tel, 608)
        wear = [_d(tel, 848 + w * 260 + 152) for w in range(4)]
        fr.tyre_wear = wear if all(0.0 <= x <= 1.0 for x in wear) else None
        fr.tyre_wear_frac = True
        fr.damage = min(1.0, sum(tel[544:552]) / 8.0)
        water, oil = _d(tel, 364), _d(tel, 372)
        fr.water_temp = water if 1.0 < water < 250.0 else None
        fr.oil_temp = oil if 1.0 < oil < 250.0 else None
        rain, wet = _d(sc_info, 220), _d(sc_info, 332)
        if 0.0 <= rain <= 1.0 and 0.0 <= wet <= 1.0:
            fr.rain = max(rain, wet if wet >= 0.15 else 0.0)
            fr.precip = rain
        mx, _my, mz = fr.pos = _U_3d(tel, 160)
        me = _i(tel, 0)
        fr.field = _RF2Family._field(vehicles, lap_len, me)
        v_by_id = None
        others_pos, others_meta = [], []
        for t in telems:
            tid = _i(t, 0)
            if tid != me:
                tp = _U_3d(t, 160)
                ddx, ddz = abs(tp[0] - mx), abs(tp[2] - mz)
                if ddx <= 10.0 and ddz <= 10.0:
                    others_pos.append(tp)
                if ddx <= 25.0 and ddz <= 25.0:
                    if v_by_id is None:
                        v_by_id = {_i(v, 0): v for v in vehicles}
                    vv = v_by_id.get(tid)
                    if vv is not None:
                        others_meta.append({"pos": tp, "name": _cstr(vv, 4, 32), "position": max(0, int(_U_b(vv, 199)[0])),
                                            "car": nice_name(_cstr(vv, 36, 64))})
        fr.others = others_pos
        if others_meta:
            fr.others_meta = others_meta
        return fr

    @staticmethod
    def _field(vehicles, lap_len, me):
        """Every car from VehicleScoringInfoV01: mID @0, mDriverName @4, mVehicleName @36, mTotalLaps @100,
        mFinishStatus @103 (0 none, 1 finished, 2 DNF, 3 DQ), mLapDist @104, mBestLapTime @144, mLastLapTime @168,
        mNumPitstops @192, mInPits @198, mPlace @199, mVehicleClass @200."""
        out = []
        for v in vehicles:
            vid = _i(v, 0)
            fin = _U_b(v, 103)[0]
            out.append(field_entry(vid, _cstr(v, 4, 32), nice_name(_cstr(v, 36, 64)), _U_b(v, 199)[0],
                                   _U_h(v, 100)[0], _d(v, 104) / lap_len if lap_len > 0 else 0.0, bool(v[198]),
                                   _d(v, 168), _d(v, 144), {1: "finished", 2: "dnf", 3: "dsq"}.get(fin),
                                   _U_h(v, 192)[0], player=vid == me, cls=_cstr(v, 200, 32)))
        return out

    def _paused(self, tel):
        """True when the telemetry clock (TelemInfoV01.mElapsedTime) hasn't moved for half a second: the game is
        paused and the block just holds the last frame (mInRealtime stays set while paused)."""
        et, now = _d(tel, 12), time.monotonic()
        if et != getattr(self, "_et", None):
            self._et, self._et_t = et, now
            return False
        return now - self._et_t > 0.5

    def _vehicle_frame(self, game, sc_info, veh, tel, invalid):
        lap_len = _d(sc_info, 88)
        lapdist = _d(veh, 104)
        vx, vy, vz = _U_3d(tel, 184)
        temps, press, wk, spins = [], [], [], []
        radii_ok = True
        for w in range(4):
            wb = 848 + w * 260
            temps.append(_d(tel, wb + 136) - 273.15)
            press.append(_d(tel, wb + 120) * 0.145038)
            r = tel[wb + 179] / 100.0
            if r <= 0.1:
                radii_ok = False
            spin = _d(tel, wb + 40)
            spins.append(spin)
            wk.append(abs(spin) * r * 3.6 if r > 0.1 else 0.0)
        spd = math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6
        thr, brk = _d(tel, 388), _d(tel, 396)
        if not radii_ok:
            cal = getattr(self, "_wcal", None)
            if cal is None:
                cal = self._wcal = _WheelCal()
            if getattr(self, "_wcal_car", None) != tel[32:96]:
                self._wcal_car = tel[32:96]
                cal.reset()
            wk = cal.update(spd, thr, brk, spins)
        fr = Frame(game, _cstr(sc_info, 0, 64), _cstr(tel, 32, 64), max(0, _U_h(veh, 100)[0]),
                   (lapdist / lap_len) % 1.0 if lap_len > 0 else 0.0, spd,
                   thr, brk, _d(tel, 404), _i(tel, 352), _d(tel, 356),
                   max(0.0, _d(veh, 464)), max(0.0, _d(veh, 168)), bool(veh[198]), False, _d(tel, 524),
                   lap_len if lap_len > 500 else None, temps if all(t > -50 for t in temps) else None,
                   _d(tel, 532), wk, press)
        fr.lap_invalid = invalid
        sec = veh[102]
        local = 0 <= sec <= 2 and sc_info[110 + sec] == 2
        fr.flag = "fcy" if veh[505] else ("yellow" if local else ("blue" if veh[504] == 6 else None))
        return fr


class LMUReader(_RF2Family):
    name = "LMU"
    CAP_BLOCKS = (("LMU_Data", "m", None),)
    SIZE = 324824

    def __init__(self):
        self.m = None
        self.lk, self._lk_retry, self._busy_skips = None, 0.0, 0

    def close(self):
        if self.m:
            self.m.close()
            self.m = None
        if self.lk:
            self.lk.close()
            self.lk = None

    def connected(self):
        if not running("le mans ultimate", "lmu.exe"):
            self.close()
            return False
        if self.m is None:
            self.m = SharedMem.open("LMU_Data")
        return self.m is not None

    def _busy(self):
        """LMU's write lock (LMU_SharedMemoryLockData: LONG waiters, LONG busy) is held while the game copies a new
        frame in. Only peeked at, never taken: a frame read while it's held is skipped (at most 3 in a row)."""
        if self.lk is None:
            now = time.monotonic()
            if now < self._lk_retry:
                return False
            self._lk_retry = now + 5.0
            self.lk = SharedMem.open("LMU_SharedMemoryLockData")
            if self.lk is None:
                return False
        return _i(self.lk[0:8], 4) != 0

    def read(self):
        busy = self._busy()
        if busy and self._busy_skips < 3:
            self._busy_skips += 1
            return None
        if not busy:
            self._busy_skips = 0
        b = self.m
        sc = b[1632:1632 + 548]
        if not sc[115]:
            return None
        hdr = b[128464:128468]
        if not hdr[2]:
            return None
        nt, idx = min(104, hdr[0]), hdr[1]
        if idx >= 104:
            return None
        n = min(104, _i(sc, 104))
        block = _span(b, 2192, n * 584)
        vehicles = [block[i * 584:(i + 1) * 584] for i in range(n)]
        veh = next((v for v in vehicles if v[196]), None)
        if veh is None:
            return None
        veh = bytes(veh)
        tel_off = 128468 + idx * 1888
        tel = b[tel_off:tel_off + 1888]
        t_all = _span(b, 128468, nt * 1888)
        vid = _i(veh, 0)
        if idx >= nt or _i(tel, 0) != vid:
            k = next((i for i in range(nt) if _i(t_all, i * 1888) == vid), None)
            if k is None:
                return None
            tel = b[128468 + k * 1888:128468 + (k + 1) * 1888]
        if self._paused(tel):
            return None
        fr = self._vehicle_frame("LMU", sc, veh, tel, bool(tel[745]))
        telems = [t_all[i * 1888:i * 1888 + 184] for i in range(nt)]
        fr = self._race_state(fr, sc, veh, tel, vehicles, telems)
        self._lmu_extras(fr, tel)
        if not busy and self._busy() and self._busy_skips < 3:
            self._busy_skips += 1
            return None
        self._busy_skips = 0
        return fr


    def _lmu_extras(self, fr, tel):
        """LMU's own additions to TelemInfoV01 (offsets from LMU's InternalsPlugin.hpp): mTrackLimitsSteps @767 (uint8),
        mVirtualEnergy @776 (float). VE comes as a fraction or a percent: once a value above 1.5 has been seen for this
        car it's a percent. A car that has never shown any VE doesn't use it (0 = not this class)."""
        car = tel[32:96]
        if car != getattr(self, "_ve_car", None):
            self._ve_car, self._ve_pct, self._ve_seen = car, False, False
        ve = _f(tel, 776)
        if not (0.0 <= ve <= 105.0):
            ve = None
        elif ve > 1.5:
            self._ve_pct = True
        if ve is not None and self._ve_pct:
            ve /= 100.0
        if ve is not None and ve > 0.002:
            self._ve_seen = True
        if ve is not None and self._ve_seen and ve <= 1.05:
            fr.energy = ve
        fr.track_limits = tel[767]


class RF2Reader(_RF2Family):
    """Needs rFactor2SharedMemoryMapPlugin64 enabled in rF2 (it's installed in Bin64\\Plugins)."""
    name = "rFactor 2"
    CAP_BLOCKS = (("telemetry", "t", None), ("scoring", "s", None))

    def __init__(self):
        self.t = self.s = None
        self._cl_lap, self._cl_ok = None, False

    def close(self):
        for blk in (self.t, self.s):
            if blk:
                blk.close()
        self.t = self.s = None
        self._cl_lap, self._cl_ok = None, False

    def connected(self):
        if not running("rfactor2.exe"):
            self.close()
            return False
        if self.t is None or self.s is None:
            self.close()
            t = SharedMem.open("$rFactor2SMMP_Telemetry$")
            s = SharedMem.open("$rFactor2SMMP_Scoring$")
            if t and s:
                self.t, self.s = t, s
            else:
                if t:
                    t.close()
                if s:
                    s.close()
        return self.t is not None and self.s is not None

    @staticmethod
    def _versions(s, t):
        """The plugin bumps mVersionUpdateBegin before writing a buffer and mVersionUpdateEnd after it's done.
        Both buffers' versions, or None while either one is being written."""
        sb, se = _U_II(s[0:8], 0)
        tb, te = _U_II(t[0:8], 0)
        return (sb, tb) if sb == se and tb == te else None

    def read(self):
        s, t = self.s, self.t
        torn = getattr(self, "_torn", 0)
        v0 = self._versions(s, t)
        if v0 is None and torn < 3:
            self._torn = torn + 1
            return None
        fr = self._read(s, t)
        if v0 is not None and self._versions(s, t) != v0 and torn < 3:
            self._torn = torn + 1
            return None
        self._torn = 0
        return fr

    def _read(self, s, t):
        sc = s[12:12 + 548]
        if not sc[115]:
            return None
        nv = min(128, _i(sc, 104))
        block = _span(s, 560, nv * 584)
        vehicles = [block[i * 584:(i + 1) * 584] for i in range(nv)]
        veh = next((v for v in vehicles if v[196]), None)
        if veh is None:
            return None
        veh = bytes(veh)
        vid = _i(veh, 0)
        cl, lapn = veh[506], _U_h(veh, 100)[0]
        if lapn != self._cl_lap:
            self._cl_lap, self._cl_ok = lapn, False
        if cl == 2:
            self._cl_ok = True
        lap_inv = self._cl_ok and cl < 2
        nt = max(0, min(128, _i(t[12:16], 0)))
        t_block = _span(t, 16, nt * 1888)
        for i in range(nt):
            tb = i * 1888
            if _i(t_block, tb) == vid:
                tel = bytes(t_block[tb:tb + 1888])
                if self._paused(tel):
                    return None
                fr = self._vehicle_frame("rFactor 2", sc, veh, tel, lap_inv)
                telems = [t_block[k * 1888:k * 1888 + 184] for k in range(nt)]
                return self._race_state(fr, sc, veh, tel, vehicles, telems)
        return None



class AMS2Reader(Reader):
    """In AMS2: Options > System > Shared Memory = 'Project CARS 2'."""
    name = "AMS2"
    CAP_BLOCKS = (("pcars2", "m", None),)

    def __init__(self):
        self.m = None
        self._torn = 0
        self._wcal, self._wcal_car = _WheelCal(), None
        self._tl = None
        self._tl_scale = None

    def close(self):
        if self.m:
            self.m.close()
            self.m = None

    def connected(self):
        if not running("ams2"):
            self.close()
            return False
        if self.m is None:
            self.m = SharedMem.open("$pcars2$")
        return self.m is not None

    def _time_left(self, raw, ses, now):
        """mEventTimeRemaining: SharedMemory.h says milliseconds, some builds send seconds. Worked out from how fast
        it counts down (1000 a second = ms); anything over a day can only be ms."""
        if raw <= 0:
            return None
        cal = self._tl
        if cal is None or cal[2] != ses or raw > cal[1] + 5.0:
            self._tl, self._tl_scale = (now, raw, ses), None
        elif self._tl_scale is None and now - cal[0] >= 3.0:
            rate = (cal[1] - raw) / (now - cal[0])
            if rate > 100.0:
                self._tl_scale = 0.001
            elif 0.3 < rate < 3.0:
                self._tl_scale = 1.0
        scale = self._tl_scale or (0.001 if raw > 86400.0 else None)
        return raw * scale if scale else None

    def read(self):
        m = self.m
        s0 = _U_I(m[7320:7324], 0)[0]
        b = m[:20700]
        if (s0 & 1 or _U_I(m[7320:7324], 0)[0] != s0) and self._torn < 3:
            self._torn += 1
            return None
        self._torn = 0
        if _i(b, 8) != 2:
            return None
        idx = _i(b, 20)
        if not 0 <= idx < min(64, _i(b, 24)) or not b[28 + idx * 100]:
            return None
        pb = 28 + idx * 100
        tl = _f(b, 6704)
        track = _cstr(b, 6576, 64)
        var = _cstr(b, 6640, 64)
        temps = list(_U_4f(b, 20600))
        press = list(_U_4f(b, 7372))
        car = _cstr(b, 6444, 64)
        spd, thr, brk = _f(b, 6848) * 3.6, _f(b, 6864), _f(b, 6860)
        if car != self._wcal_car:
            self._wcal_car = car
            self._wcal.reset()
        wk = self._wcal.update(spd, thr, brk, _U_4f(b, 7040))
        fr = Frame("AMS2", f"{track} {var}".strip(), car, _U_I(b, pb + 88)[0],
                   (_f(b, pb + 80) / tl) % 1.0 if tl > 0 else 0.0, spd, thr, brk,
                   _f(b, 6872), _i(b, 6876), _f(b, 6852), max(0.0, _f(b, 6724)), max(0.0, _f(b, 6720)),
                   _U_I(b, 6808)[0] != 0, False, _f(b, 6840) * _f(b, 6844),
                   tl if tl > 500 else None, temps if any(t > 1 for t in temps) else None, _f(b, 6856), wk,
                   press if any(x > 5 for x in press) else None, lap_invalid=bool(b[6712]))
        ses_raw = _i(b, 12)
        race_st = _U_I(b, 16)[0]
        fr.session = {1: "practice", 2: "practice", 3: "qualifying", 4: "race", 5: "race",
                      6: "practice"}.get(ses_raw)
        n = max(0, min(64, _i(b, 24)))
        fr.position, fr.cars = _U_I(b, pb + 84)[0], n
        laps = _U_I(b, 6572)[0]
        fr.race_laps = laps if 0 < laps < 1000 else 0
        fr.race_over = bool(fr.session == "race" and (
            race_st == 3 or (fr.race_laps > 0 and fr.laps_done >= fr.race_laps)
        ))
        tleft = self._time_left(_f(b, 6740), ses_raw, time.monotonic())
        fr.time_left = tleft if tleft is not None and 0 < tleft < 86400 and not fr.race_laps else None
        ga, gb = _f(b, 6728), _f(b, 6732)
        fr.gap_ahead = ga if 0 < ga < 600 else None
        fr.gap_behind = gb if 0 < gb < 600 else None
        fr.fuel_cap = _f(b, 6844)
        wear = list(_U_4f(b, 7136))
        fr.tyre_wear = [x * 100 for x in wear] if all(0 <= x <= 1 for x in wear) else None
        dmg = [_f(b, 7284), _f(b, 7288)] + list(_U_4f(b, 7168))
        fr.damage = max(0.0, min(1.0, max(dmg)))
        fr.rain = max(0.0, min(1.0, _f(b, 7300)))
        oil, water = _f(b, 6820), _f(b, 6828)
        fr.oil_temp = oil if 1.0 < oil < 250.0 else None
        fr.water_temp = water if 1.0 < water < 250.0 else None
        fc = _U_I(b, 6800)[0]
        fr.flag = "blue" if fc == 2 else ("yellow" if fc in (6, 7) else None)
        fr.pos = _U_3f(b, pb + 68)
        my_lap_d = _f(b, pb + 80)
        tlen = tl if tl > 500 else 4000.0
        fr.field = _ams2_field(b, n, idx, tlen)
        others_pos, others_meta = [], []
        for k in range(n):
            ob = 28 + k * 100
            if k == idx or not b[ob]:
                continue
            opos = _U_3f(b, ob + 68)
            ddx, ddz = abs(opos[0] - fr.pos[0]), abs(opos[2] - fr.pos[2])
            if ddx <= 10.0 and ddz <= 10.0:
                others_pos.append(opos)
            orace_pos = int(_U_I(b, ob + 84)[0])
            near = ddx <= 25.0 and ddz <= 25.0
            if not (near or (fr.position and orace_pos > 0 and abs(orace_pos - fr.position) == 1)):
                continue
            oname = _cstr(b, ob + 1, 64)
            ocar = nice_name(_cstr(b, 11056 + k * 64, 64)) or nice_name(fr.car)
            if near:
                others_meta.append({"pos": opos, "name": oname, "position": orace_pos, "car": ocar})
            olap_d = _f(b, ob + 80)
            if fr.position > 1 and orace_pos == fr.position - 1:
                dm = (olap_d - my_lap_d) % tlen
                if dm <= 0 or dm > tlen * 0.5:
                    dm = math.hypot(opos[0] - fr.pos[0], opos[2] - fr.pos[2])
                fr.car_ahead = {"name": oname, "position": orace_pos, "car": ocar,
                                "distance_m": round(max(1.0, dm)), "gap_s": fr.gap_ahead}
            elif fr.position >= 1 and orace_pos == fr.position + 1:
                dm = (my_lap_d - olap_d) % tlen
                if dm <= 0 or dm > tlen * 0.5:
                    dm = math.hypot(opos[0] - fr.pos[0], opos[2] - fr.pos[2])
                fr.car_behind = {"name": oname, "position": orace_pos, "car": ocar,
                                 "distance_m": round(max(1.0, dm)), "gap_s": fr.gap_behind}
        fr.others = others_pos
        if others_meta:
            fr.others_meta = others_meta
        return fr



def _ams2_field(b, n, idx, tlen):
    """Every active participant (ParticipantInfo, 100 bytes from @28: mIsActive @0, mName @1, mCurrentLapDistance
    @80, mRacePosition @84, mLapsCompleted @88) plus the per-car arrays of SharedMemory.h v2: mFastestLapTimes @8944,
    mLastLapTimes @9200, mRaceStates @9520 (3 finished, 4 DQ, 5 retired, 6 DNF), mPitModes @9776 (1-5: pit lane or
    garage), mSpeeds @10800 (m/s), mCarNames @11056, mCarClassNames @15152."""
    out = []
    for k in range(n):
        ob = 28 + k * 100
        if not b[ob]:
            continue
        st = _U_I(b, 9520 + 4 * k)[0]
        out.append(field_entry(k, _cstr(b, ob + 1, 64), nice_name(_cstr(b, 11056 + k * 64, 64)),
                               _U_I(b, ob + 84)[0], _U_I(b, ob + 88)[0], _f(b, ob + 80) / tlen,
                               1 <= _U_I(b, 9776 + 4 * k)[0] <= 5, _f(b, 9200 + 4 * k), _f(b, 8944 + 4 * k),
                               {3: "finished", 4: "dsq", 5: "dnf", 6: "dnf"}.get(st), player=k == idx,
                               speed=_f(b, 10800 + 4 * k) * 3.6, cls=_cstr(b, 15152 + k * 64, 64)))
    return out


class R3EReader(Reader):
    name = "RaceRoom"
    CAP_BLOCKS = (("r3e", "m", None),)

    def __init__(self):
        self.m = None

    def close(self):
        if self.m:
            self.m.close()
            self.m = None

    def connected(self):
        if not running("rrre"):
            self.close()
            return False
        if self.m is None:
            self.m = SharedMem.open("$R3E")
        return self.m is not None

    def read(self):
        b = self.m[:44024]
        if _i(b, 0) != 3 or _i(b, 20) or _i(b, 24) or _i(b, 28) or _i(b, 780) == -1:
            return None
        tl = _f(b, 736)
        temps = [_f(b, 1744 + w * 24 + 4) for w in range(4)]
        press = [_f(b, 1712 + w * 4) * 0.145038 for w in range(4)]
        track = f"{_cstr(b, 600, 64)} {_cstr(b, 664, 64)}".strip()
        ts = _U_4f(b, 1648)
        wk = [abs(x) * 3.6 for x in ts] if all(x != -1.0 and x == x for x in ts) else None
        fr = Frame("RaceRoom", track, raceroom_car(_i(b, 1196 + 72)), max(0, _i(b, 1028)), max(0.0, _f(b, 1044)) % 1.0,
                   _f(b, 1392) * 3.6, _f(b, 1504), _f(b, 1512), _f(b, 1524), _i(b, 1408),
                   _f(b, 1396) * 60 / (2 * math.pi), max(0.0, _f(b, 1100)), max(0.0, _f(b, 1084)),
                   _i(b, 848) > 0, False, _f(b, 1456), tl if tl > 500 else None,
                   temps if any(t > 1 for t in temps) else None, _f(b, 1400) * 60 / (2 * math.pi), wk,
                   press if any(x > 5 for x in press) else None, lap_invalid=_i(b, 1032) == 0)
        fr.session = {0: "practice", 1: "qualifying", 2: "race", 3: "practice"}.get(_i(b, 780))
        fin_st = _i(b, 996)
        laps = _i(b, 812)
        fr.race_laps = laps if 0 < laps < 1000 else 0
        fr.race_over = bool(fr.session == "race" and (
            fin_st == 1 or (fr.race_laps > 0 and fr.laps_done >= fr.race_laps)
        ))
        tleft = _f(b, 820)
        fr.time_left = tleft if 0 < tleft < 86400 and not fr.race_laps else None
        me, n = max(0, _i(b, 988)), max(0, min(128, _i(b, 2008)))
        fr.position, fr.cars = me, n
        ga, gb = _f(b, 1124), _f(b, 1128)
        fr.gap_ahead = ga if 0 < ga < 600 else None
        fr.gap_behind = gb if 0 < gb < 600 else None
        fr.fuel_cap = _f(b, 1460)
        fr.flag = "yellow" if _i(b, 932) == 1 else ("blue" if _i(b, 964) == 1 else None)
        water, oil = _f(b, 1480), _f(b, 1484)
        fr.water_temp = water if 1.0 < water < 250.0 else None
        fr.oil_temp = oil if 1.0 < oil < 250.0 else None
        ve, ve_cap, ve_lap = _f(b, 1468), _f(b, 1472), _f(b, 1476)
        if ve_cap > 0.0 and 0.0 <= ve <= ve_cap * 1.05:
            fr.energy = ve / ve_cap
            if 0.0 < ve_lap < ve_cap:
                fr.energy_lap = ve_lap / ve_cap
        wear = list(_U_4f(b, 1680))
        fr.tyre_wear = wear if all(0.0 <= x <= 1.0 for x in wear) else None
        fr.tyre_wear_frac = True
        dmg = [x for x in _U_4f(b, 1984) if 0.0 <= x <= 1.0]
        fr.damage = 1.0 - min(dmg) if dmg else None
        fr.pos = _U_3d(b, 56)
        tlen = tl if tl > 500 else 4000.0
        my_d = fr.pct * tlen
        fr.field = _r3e_field(b, n, me, tlen)
        others_pos, others_meta = [], []
        for k in range(n):
            ob = 2012 + k * 328
            plc = _i(b, ob + 132)
            opos = _U_3f(b, ob + 148)
            ddx, ddz = abs(opos[0] - fr.pos[0]), abs(opos[2] - fr.pos[2])
            if (me > 0 and plc == me) or (me == 0 and ddx < 0.5 and ddz < 0.5):
                if _i(b, ob + 128) == 1 and fr.session == "race":
                    fr.race_over = True
                continue
            if ddx <= 10.0 and ddz <= 10.0:
                others_pos.append(opos)
            near = ddx <= 25.0 and ddz <= 25.0
            if not (near or (me > 0 and plc > 0 and abs(plc - me) == 1)):
                continue
            oname = _cstr(b, ob, 64)
            ocar = f"car {_i(b, ob + 72)}"
            if near:
                others_meta.append({"pos": opos, "name": oname, "position": max(0, plc), "car": ocar})
            odist = _f(b, ob + 140)
            if me > 1 and plc == me - 1:
                dm = (odist - my_d) % tlen if odist > 0 else math.hypot(opos[0] - fr.pos[0], opos[2] - fr.pos[2])
                fr.car_ahead = {"name": oname, "position": plc, "car": ocar,
                                "distance_m": round(max(1.0, dm)), "gap_s": fr.gap_ahead}
            elif me >= 1 and plc == me + 1:
                dm = (my_d - odist) % tlen if odist > 0 else math.hypot(opos[0] - fr.pos[0], opos[2] - fr.pos[2])
                fr.car_behind = {"name": oname, "position": plc, "car": ocar,
                                 "distance_m": round(max(1.0, dm)), "gap_s": fr.gap_behind}
        fr.others = others_pos
        if others_meta:
            fr.others_meta = others_meta
        return fr



def _r3e_field(b, n, me, tlen):
    """Every car (DriverData, 328 bytes from @2012, r3e.h): name @0, model_id @72, finish_status @128 (1 finished,
    2 DNF, 5 DQ), place @132, lap_distance @140, completed_laps @164, sector_time_previous_self[2] @196 (last lap),
    sector_time_best_self[2] @208 (best lap), in_pitlane @224, num_pitstops @228, car_speed @252 (m/s)."""
    out = []
    for k in range(n):
        ob = 2012 + k * 328
        plc = _i(b, ob + 132)
        if plc <= 0:
            continue
        car = raceroom_car(_i(b, ob + 72))
        out.append(field_entry(_i(b, ob + 92) or k, _cstr(b, ob, 64), car, plc, _i(b, ob + 164),
                               _f(b, ob + 140) / tlen, _i(b, ob + 224) > 0, _f(b, ob + 196), _f(b, ob + 208),
                               {1: "finished", 2: "dnf", 5: "dsq"}.get(_i(b, ob + 128)), _i(b, ob + 228),
                               player=plc == me, speed=_f(b, ob + 252) * 3.6, cls=raceroom_class(car)))
    return out


IRSDK_MMF = "Local\\IRSDKMemMapFileName"
_IR_HDR = struct.Struct("<10i")            # ver, status, tickRate, sessionInfoUpdate, sessionInfoLen, sessionInfoOffset,
                                            # numVars, varHeaderOffset, numBuf, bufLen
_IR_VARBUF = struct.Struct("<2i")          # tickCount, bufOffset (then 2 pad ints); 4 of them from offset 48
_IR_VARHDR = struct.Struct("<3i?3x32s")    # type, offset, count, countAsTime, name (desc/unit follow; 144 bytes each)
_IR_FMT = {0: "c", 1: "?", 2: "i", 3: "I", 4: "f", 5: "d"}
_IR_SIZE = {0: 1, 1: 1, 2: 4, 3: 4, 4: 4, 5: 8}
# irsdk_Flags
_IR_FLAG_YELLOW, _IR_FLAG_BLUE, _IR_FLAG_YELLOW_WAVING = 0x8, 0x20, 0x100
_IR_FLAG_CAUTION, _IR_FLAG_CAUTION_WAVING = 0x4000, 0x8000


def _ir_session_info(text):
    """The few fields SimCoach needs from iRacing's session YAML, without a YAML library."""
    def field(name, src=text):
        m = re.search(rf"^\s*{name}:\s*(.*?)\s*$", src, re.MULTILINE)
        return m.group(1).strip().strip('"') if m else None

    def num(v):
        m = re.match(r"-?\d+(?:\.\d+)?", v or "")
        return float(m.group(0)) if m else None
    info = {"track": field("TrackDisplayName") or field("TrackName") or "iRacing track"}
    km = num(field("TrackLength"))
    info["track_len"] = km * 1000.0 if km else None
    info["redline"] = num(field("DriverCarRedLine")) or 0.0
    info["fuel_cap"] = num(field("DriverCarFuelMaxLtr")) or 0.0
    me = num(field("DriverCarIdx"))
    info["car_idx"] = int(me) if me is not None else None
    info["car"], cars, drivers = "iRacing car", 0, {}
    for blk in re.split(r"^\s*-\s+CarIdx:\s*", text, flags=re.MULTILINE)[1:]:
        idx = num(blk.split("\n", 1)[0])
        body = blk.split("\n- ", 1)[0]
        if idx is None:
            continue
        name = field("UserName", body) or ""
        skip = field("CarIsPaceCar", body) == "1" or field("IsSpectator", body) == "1"
        drivers[int(idx)] = {"name": name, "car": field("CarScreenName", body) or "", "skip": skip,
                             "cls": field("CarClassShortName", body) or ""}
        if skip:
            continue
        cars += 1
        if info["car_idx"] is not None and int(idx) == info["car_idx"]:
            info["car"] = field("CarScreenName", body) or info["car"]
    info["cars"], info["drivers"] = cars, drivers
    sessions = {}
    for blk in re.split(r"^\s*-\s+SessionNum:\s*", text, flags=re.MULTILINE)[1:]:
        n = num(blk.split("\n", 1)[0])
        if n is None:
            continue
        typ = (field("SessionType", blk) or "").lower()
        laps = num(field("SessionLaps", blk))
        sessions[int(n)] = {"type": "race" if "race" in typ else ("qualifying" if "qual" in typ else "practice"),
                            "laps": int(laps) if laps else 0}
    info["sessions"] = sessions
    return info


class IRacingReader(Reader):
    """iRacing through its SDK shared memory: a header, variable descriptions, rotating data buffers (the newest
    one is read) and a YAML text block with track, car and session details."""
    name = "iRacing"
    CAP_BLOCKS = (("irsdk", "m", None),)
    WANT = ("Speed", "Throttle", "Brake", "SteeringWheelAngle", "SteeringWheelAngleMax", "Gear", "RPM",
            "LapDistPct", "LapCompleted", "LapCurrentLapTime", "LapLastLapTime", "OnPitRoad", "PlayerTrackSurface",
            "FuelLevel", "PlayerCarPosition", "PlayerCarIdx", "SessionNum", "SessionState", "SessionFlags",
            "SessionTimeRemain", "WaterTemp", "OilTemp", "CarIdxPosition", "CarIdxF2Time", "IsOnTrack",
            "CarIdxLapDistPct", "CarIdxLapCompleted", "CarIdxOnPitRoad", "CarIdxLastLapTime", "CarIdxBestLapTime",
            "CarIdxTrackSurface")

    def __init__(self):
        self.m = None
        self._vars, self._layout_key = {}, None
        self._info, self._info_upd = None, None

    def close(self):
        if self.m:
            self.m.close()
            self.m = None
        self._vars, self._layout_key, self._info, self._info_upd = {}, None, None, None

    def connected(self):
        if not running("iracingsim"):
            self.close()
            return False
        if self.m is None:
            self.m = SharedMem.open(IRSDK_MMF)
        if self.m is None:
            return False
        return bool(_IR_HDR.unpack_from(self.m[0:40], 0)[1] & 1)

    def _load_vars(self, hdr):
        n_vars, vh_off = hdr[6], hdr[7]
        if (n_vars, vh_off) == self._layout_key:
            return
        raw = self.m[vh_off:vh_off + n_vars * 144]
        out = {}
        for k in range(n_vars):
            typ, off, cnt, _ast, name = _IR_VARHDR.unpack_from(raw, k * 144)
            name = name.split(b"\0", 1)[0].decode("latin-1")
            if name in self.WANT and typ in _IR_FMT:
                out[name] = (typ, off, max(1, cnt))
        self._vars, self._layout_key = out, (n_vars, vh_off)

    def _get(self, buf, name, default=None):
        v = self._vars.get(name)
        if v is None:
            return default
        typ, off, cnt = v
        if cnt == 1:
            return struct.unpack_from("<" + _IR_FMT[typ], buf, off)[0]
        return struct.unpack_from(f"<{cnt}{_IR_FMT[typ]}", buf, off)

    def read(self):
        hdr = _IR_HDR.unpack_from(self.m[0:40], 0)
        if not hdr[1] & 1 or hdr[8] < 1 or hdr[9] <= 0:
            return None
        self._load_vars(hdr)
        if hdr[3] != self._info_upd or self._info is None:
            raw = self.m[hdr[5]:hdr[5] + hdr[4]].split(b"\0", 1)[0]
            self._info, self._info_upd = _ir_session_info(raw.decode("latin-1", "replace")), hdr[3]
        bufs = [_IR_VARBUF.unpack_from(self.m[48 + 16 * k:48 + 16 * k + 8], 0) for k in range(min(4, hdr[8]))]
        tick, off = max(bufs)
        slot = 48 + 16 * bufs.index((tick, off))
        buf = self.m[off:off + hdr[9]]
        if _IR_VARBUF.unpack_from(self.m[slot:slot + 8], 0)[0] != tick:
            return None                                   # iRacing rewrote that buffer while we copied it: next frame
        g = lambda n, d=None: self._get(buf, n, d)
        info = self._info
        ses = info["sessions"].get(g("SessionNum", 0) or 0, {"type": "practice", "laps": 0})
        smax = g("SteeringWheelAngleMax", 0.0) or 0.0
        surf = g("PlayerTrackSurface", 3)
        laps_done = max(0, g("LapCompleted", 0) or 0)
        fr = Frame("iRacing", info["track"], info["car"], laps_done, max(0.0, min(0.99999, g("LapDistPct", 0.0) or 0.0)),
                   (g("Speed", 0.0) or 0.0) * 3.6, g("Throttle", 0.0) or 0.0, g("Brake", 0.0) or 0.0,
                   (-(g("SteeringWheelAngle", 0.0) or 0.0) / smax) if smax > 0.1 else 0.0,
                   g("Gear", 0) or 0, g("RPM", 0.0) or 0.0, max(0.0, g("LapCurrentLapTime", 0.0) or 0.0),
                   max(0.0, g("LapLastLapTime", 0.0) or 0.0), bool(g("OnPitRoad", False)) or surf in (1, 2), surf == 0,
                   fuel=max(0.0, g("FuelLevel", 0.0) or 0.0), track_len=info["track_len"], max_rpm=info["redline"],
                   session=ses["type"], position=max(0, g("PlayerCarPosition", 0) or 0), cars=info["cars"],
                   race_laps=ses["laps"] if ses["type"] == "race" else 0, fuel_cap=info["fuel_cap"])
        tleft = g("SessionTimeRemain")
        fr.time_left = tleft if (tleft is not None and 0 < tleft < 86400 and not fr.race_laps) else None
        fr.race_over = bool(ses["type"] == "race" and (g("SessionState", 0) or 0) >= 5)
        water, oil = g("WaterTemp"), g("OilTemp")
        fr.water_temp = water if water and 1.0 < water < 250.0 else None
        fr.oil_temp = oil if oil and 1.0 < oil < 250.0 else None
        fl = g("SessionFlags", 0) or 0
        fr.flag = ("fcy" if fl & (_IR_FLAG_CAUTION | _IR_FLAG_CAUTION_WAVING) else
                   "yellow" if fl & (_IR_FLAG_YELLOW | _IR_FLAG_YELLOW_WAVING) else
                   "blue" if fl & _IR_FLAG_BLUE else None)
        me, pos, f2 = g("PlayerCarIdx"), g("CarIdxPosition"), g("CarIdxF2Time")
        if me is not None and pos and f2 and 0 <= me < len(pos) and fr.position > 0 and ses["type"] == "race":
            by_pos = {p: i for i, p in enumerate(pos) if p > 0}
            mine = f2[me]
            a, b = by_pos.get(fr.position - 1), by_pos.get(fr.position + 1)
            ga = mine - f2[a] if a is not None else None
            gb = f2[b] - mine if b is not None else None
            fr.gap_ahead = ga if ga is not None and 0 < ga < 600 else None
            fr.gap_behind = gb if gb is not None and 0 < gb < 600 else None
            names = info["drivers"]
            if a is not None and fr.gap_ahead:
                fr.car_ahead = {"name": names.get(a, {}).get("name", ""), "position": fr.position - 1,
                                "car": names.get(a, {}).get("car", ""), "gap_s": fr.gap_ahead}
            if b is not None and fr.gap_behind:
                fr.car_behind = {"name": names.get(b, {}).get("name", ""), "position": fr.position + 1,
                                 "car": names.get(b, {}).get("car", ""), "gap_s": fr.gap_behind}
        fr.field = self._field(g, info, me, pos)
        return fr

    @staticmethod
    def _field(g, info, me, pos):
        """Every car from the CarIdx arrays (TrackSurface -1: not in the world, so left out)."""
        pct, done, pit = g("CarIdxLapDistPct"), g("CarIdxLapCompleted"), g("CarIdxOnPitRoad")
        if not pct or not done or not pos:
            return None
        last, best, surf = g("CarIdxLastLapTime"), g("CarIdxBestLapTime"), g("CarIdxTrackSurface")
        out = []
        for idx, d in info["drivers"].items():
            if d.get("skip") or not 0 <= idx < len(pct) or (surf and idx < len(surf) and surf[idx] < 0):
                continue
            out.append(field_entry(idx, d.get("name"), d.get("car"), pos[idx] if idx < len(pos) else 0,
                                   done[idx], pct[idx], bool(pit[idx]) if pit and idx < len(pit) else False,
                                   last[idx] if last and idx < len(last) else None,
                                   best[idx] if best and idx < len(best) else None, player=idx == me,
                                   cls=d.get("cls")))
        return out


def _udp_owner(port):
    """(local ip, process name) of another program's UDP socket on `port`, or None."""
    try:
        import psutil
        me = os.getpid()
        for c in psutil.net_connections(kind="udp4"):
            if c.laddr and c.laddr.port == port and c.pid and c.pid != me:
                try:
                    name = psutil.Process(c.pid).name()
                except Exception:
                    name = "?"
                return c.laddr.ip, name
    except Exception:
        pass
    return None


def _no_connreset(sock):
    """Windows: a UDP send to a closed port makes the next recv fail (WSAECONNRESET). Turn that off."""
    try:
        import socket
        sock.ioctl(socket.SIO_UDP_CONNRESET, False)
    except Exception:
        pass


class _UDPPort:
    """One socket per UDP port, shared by every reader that wants it (F1 25 and DiRT Rally 2.0 can both use 20777).
    - Port free: bind 127.0.0.1:<port> normally ("direct").
    - SimHub running and listening on 0.0.0.0:<port>: bind 127.0.0.1:<port> with SO_REUSEADDR and pass every packet
      on to 127.0.0.2:<port>, which SimHub's 0.0.0.0 socket receives and ours doesn't, so both get the stream and
      nothing loops ("relay"). Only done when SimHub's socket is a wildcard one; anything else is left alone.
    - SimHub starts while we hold the port: release it so SimHub can bind, then join as a relay.
    - Never raises: if the port can't be used, the reader keeps working from its fallback port."""
    _ports, _lock = {}, threading.Lock()
    log = staticmethod(file_log)
    share = True

    @classmethod
    def subscribe(cls, port, reader, primary):
        with cls._lock:
            hub = cls._ports.get(port)
            if hub is None:
                hub = cls._ports[port] = cls(port)
            if primary and getattr(reader, "share_port", True):
                hub.primary = True
                hub.procs = tuple(set(hub.procs) | set(getattr(reader, "procs", ())))
            hub.readers.add(reader)
            hub.start()
        return hub

    @classmethod
    def unsubscribe(cls, port, reader):
        with cls._lock:
            hub = cls._ports.get(port)
            if hub is not None:
                hub.readers.discard(reader)
                if not hub.readers:
                    hub.close()
                    del cls._ports[port]

    def __init__(self, port):
        self.port, self.primary, self.readers = port, False, set()
        self.procs = ()
        self.sock = self.out = None
        self.mode = None
        self.wait_until = 0.0
        self.simhub_was = None
        self.game_since = None
        self._closed = False
        self._said = None
        self._started = False

    def start(self):
        if not self._started:
            self._started = True
            threading.Thread(target=self._run, daemon=True, name=f"udp-{self.port}").start()

    def _note(self, msg):
        if msg != self._said:
            self._said = msg
            self.log(f"UDP {self.port}: {msg}")

    def _bind(self, reuse):
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if reuse:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", self.port))
        except OSError:
            s.close()
            return None
        s.settimeout(0.5)
        _no_connreset(s)
        return s

    def _drop(self):
        for x in (self.sock, self.out):
            try:
                if x is not None:
                    x.close()
            except Exception:
                pass
        self.sock = self.out = None
        self.mode = None

    def _manage(self, now):
        """Private ports (EA WRC's 20790, fallbacks): just bind. Ports SimHub may use (20777):
        - SimHub not running: bind directly. If SimHub starts later, hand the port over once.
        - SimHub running: relay if it holds the port on 0.0.0.0. Otherwise wait until the game is running and give
          SimHub ~10 s to take the port first; only then bind directly, and let go when the game closes.
          No grabbing and releasing in a loop."""
        if not self.primary:
            if self.sock is None:
                self._bind_direct()
            return
        simhub = _UDPPort.share and running("simhubwpf", "simhub.exe")
        fresh = simhub and self.simhub_was is False
        self.simhub_was = simhub
        game = running(*self.procs) if self.procs else True
        if self.game_since is None and game:
            self.game_since = now
        elif not game:
            self.game_since = None
        if not simhub:
            if self.mode == "relay":
                self._drop()
            if self.sock is None:
                self._bind_direct()
            return
        if self.mode == "direct":
            if fresh:
                self._drop()
                self.wait_until = now + 15.0
                self._note("SimHub started, handing it the port.")
            elif not game:
                self._drop()
            return
        owner = _udp_owner(self.port)
        if self.mode == "relay":
            if owner is None:
                self._drop()
            return
        if owner and owner[0] in ("0.0.0.0", "::"):
            s = self._bind(reuse=True)
            if s is not None:
                import socket
                self.sock, self.mode = s, "relay"
                self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                _no_connreset(self.out)
                self._note(f"sharing with {owner[1]} (relaying to it on 127.0.0.2).")
            return
        if owner is not None:
            self._note(f"in use by {owner[1]} ({owner[0]}); using the fallback port instead.")
            return
        if game and now - self.game_since >= 10 and now >= self.wait_until:
            self._bind_direct()

    def _bind_direct(self):
        s = self._bind(reuse=False)
        if s is not None:
            self.sock, self.mode = s, "direct"
            self._note("listening.")
        else:
            owner = _udp_owner(self.port)
            who = owner[1] if owner else "another program"
            self._note(f"in use by {who}" + ("; using the fallback port instead." if self.primary else "."))

    def _run(self):
        next_check = 0.0
        while not self._closed:
            now = time.monotonic()
            if now >= next_check:
                next_check = now + 2.0
                try:
                    self._manage(now)
                except Exception as e:
                    self._note(f"error {e}")
            s = self.sock
            if s is None:
                time.sleep(0.25)
                continue
            try:
                data, _ = s.recvfrom(4096)
            except Exception:
                continue
            if self.mode == "relay" and self.out is not None:
                try:
                    self.out.sendto(data, ("127.0.0.2", self.port))
                except OSError:
                    pass
            for r in list(self.readers):
                r._feed(data)

    def close(self):
        self._closed = True
        self._drop()


class _UDPReader(Reader):
    port = 0
    fallback = None

    def __init__(self, port=None, fallback=None):
        if port:
            self.port = int(port)
        if fallback:
            self.fallback = int(fallback)
        self._closed = False
        self.last_rx = 0.0
        self.frame: Optional[Frame] = None
        self.lock = threading.Lock()
        self._plock = threading.Lock()
        self._ports = [self.port] + ([self.fallback] if self.fallback and self.fallback != self.port else [])
        self._cap_buf = None
        for i, pt in enumerate(self._ports):
            _UDPPort.subscribe(pt, self, primary=(i == 0))

    def cap_start(self):
        with self._plock:
            self._cap_buf = []

    def cap_take(self):
        """Packets received since the last call (a capture drains them a few times a second)."""
        with self._plock:
            got, self._cap_buf = self._cap_buf, ([] if self._cap_buf is not None else None)
        return got or []

    def cap_stop(self):
        with self._plock:
            self._cap_buf = None

    def _feed(self, data):
        if self._closed:
            return
        with self._plock:
            cb = self._cap_buf
            if cb is not None and len(cb) < 50000:
                cb.append((time.monotonic(), bytes(data)))
            try:
                f = self.parse(data)
            except Exception:
                f = None
            if f is not None:
                with self.lock:
                    pend = self.frame
                    if pend is not None and pend.restart and not f.restart:
                        f.restart = True
                    self.frame, self.last_rx = f, time.monotonic()

    def close(self):
        self._closed = True
        for pt in self._ports:
            _UDPPort.unsubscribe(pt, self)

    def parse(self, data):
        raise NotImplementedError

    def connected(self):
        return not self._closed and (time.monotonic() - self.last_rx < 2.0)

    def read(self):
        with self.lock:
            f, self.frame = self.frame, None
        return f


class _StageTracker:
    """Rally stages: one run = one 'lap'. Restarts without finishing are flagged, not scored."""

    def __init__(self):
        self.runs = 0
        self.prev_t = None
        self.prev_pct = 0.0
        self.last_time = 0.0
        self.key = None
        self.done = False

    def step(self, t, pct, key=None, finished=False):
        """finished: the raw stage distance reached the stage length. The run counts right there, so a
        stage that's driven once and left (next stage, results, quit) is still recorded."""
        if key != self.key:
            self.key = key
            self.runs, self.prev_t, self.prev_pct, self.last_time = 0, None, 0.0, 0.0
            self.done = False
        restart = False
        if self.prev_t is not None and t < self.prev_t - 1.0:
            if self.done:
                self.done = False
                restart = True
            elif self.prev_pct > 0.98:
                self.runs += 1
                self.last_time = self.prev_t
            else:
                restart = True
        elif finished and not self.done and t > 1.0 and self.prev_t is not None:
            self.done = True
            self.runs += 1
            self.last_time = t
        self.prev_t, self.prev_pct = t, pct
        return self.runs, self.last_time, restart


WRC_PORT = 20790
WRC_CHANNELS = [
    ("packet_uid", "Q"), ("stage_current_time", "f"), ("stage_current_distance", "d"), ("stage_length", "d"),
    ("vehicle_speed", "f"), ("vehicle_throttle", "f"), ("vehicle_brake", "f"), ("vehicle_steering", "f"),
    ("vehicle_gear_index", "B"), ("vehicle_gear_index_neutral", "B"), ("vehicle_gear_index_reverse", "B"),
    ("vehicle_engine_rpm_current", "f"), ("vehicle_engine_rpm_max", "f"),
    ("vehicle_cp_forward_speed_fl", "f"), ("vehicle_cp_forward_speed_fr", "f"),
    ("vehicle_cp_forward_speed_bl", "f"), ("vehicle_cp_forward_speed_br", "f"),
    ("vehicle_id", "H"), ("location_id", "H"), ("route_id", "H"),
]
WRC_FMT = "<" + "".join(t for _, t in WRC_CHANNELS)
_S_WRC = struct.Struct(WRC_FMT)
_WRC_SIZE = _S_WRC.size
_U_WRC = _S_WRC.unpack_from


class EAWRCReader(_UDPReader):
    name = "EA WRC"
    port = WRC_PORT
    share_port = False

    def __init__(self, port=None):
        self.stage = _StageTracker()
        self.ids = {}
        try:
            p = os.path.join(_documents_dir(), "My Games", "WRC", "telemetry", "readme", "ids.json")
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
            for k in ("vehicles", "locations", "routes"):
                self.ids[k] = {x["id"]: x.get("name", "") for x in d.get(k, [])}
        except Exception:
            pass
        super().__init__(port)

    def parse(self, data):
        if len(data) < _WRC_SIZE:
            return None
        (_uid, cur_t, cur_d, L, spd, thr, brk, steer,
         g, g_neut, g_rev, rpm, rpm_max,
         w_fl, w_fr, w_bl, w_br, vid, lid, rid) = _U_WRC(data, 0)
        if L <= 100:
            return None
        pct = max(0.0, min(0.99999, cur_d / L))
        runs, last, restart = self.stage.step(cur_t, pct, (vid, lid, rid), finished=cur_d >= L)
        gear = -1 if g == g_rev else 0 if g == g_neut else g
        sp = spd * 3.6
        wk = [abs(w_fl) * 3.6, abs(w_fr) * 3.6, abs(w_bl) * 3.6, abs(w_br) * 3.6]
        loc = self.ids.get("locations", {}).get(lid, f"location {lid}")
        route = self.ids.get("routes", {}).get(rid, f"stage {rid}")
        car = self.ids.get("vehicles", {}).get(vid, f"car {vid}")
        return Frame("EA WRC", f"{loc} - {route}", car, runs, pct, sp, thr, brk,
                     steer, gear, rpm, cur_t, last,
                     False, False, 0.0, L, None, rpm_max, wk, None, restart)


F1_TRACKS = {0: "Melbourne", 2: "Shanghai", 3: "Sakhir", 4: "Catalunya", 5: "Monaco", 6: "Montreal", 7: "Silverstone",
             9: "Hungaroring", 10: "Spa", 11: "Monza", 12: "Singapore", 13: "Suzuka", 14: "Abu Dhabi", 15: "Austin",
             16: "Interlagos", 17: "Red Bull Ring", 19: "Mexico City", 20: "Baku", 26: "Zandvoort", 27: "Imola",
             29: "Jeddah", 30: "Miami", 31: "Las Vegas", 32: "Losail", 39: "Silverstone Reverse",
             40: "Red Bull Ring Reverse", 41: "Zandvoort Reverse"}


F1_TEAMS = {0: "Mercedes", 1: "Ferrari", 2: "Red Bull", 3: "Williams", 4: "Aston Martin",
            5: "Alpine", 6: "RB", 7: "Haas", 8: "McLaren", 9: "Sauber"}


class F1Reader(_UDPReader):
    """F1 25: in-game Settings > Telemetry: UDP On, port 20777, format 2025."""
    name = "F1 25"
    port = 20777
    procs = ("f1_25", "f1_24", "f1_23")

    def __init__(self, port=None, fallback=None):
        self.track, self.track_len = "F1 circuit", None
        self.lap = None
        self.tel = None
        self.session, self.race_laps, self.time_left, self.rain = None, 0, None, None
        self.rain_in_10 = self.rain_in_30 = None
        self.fia_flag = self.sc = None
        self._sess_ok = True
        self.position, self.gap_ahead, self.gap_behind = 0, None, None
        self.fuel, self.fuel_cap, self.wear = 0.0, 0.0, None
        self.pos, self.right, self.others, self.others_meta, self.cars = None, None, None, None, 0
        self.participants = {}
        self.car_positions = {}
        self.car_laps = {}
        self.events = []
        self.race_over = False
        self.car_ahead, self.car_behind = None, None
        self._uid = None
        super().__init__(port, fallback)

    @staticmethod
    def _forecast(d, st):
        """Session packet weather forecast (F1 23-25): m_numWeatherForecastSamples @155, then up to 64 samples of 8
        bytes from @156 (sessionType, timeOffset in minutes, weather, track temp, change, air temp, change, rain %).
        The worst weather forecast for this session within 10 minutes and from 10 to 30 minutes, 0 dry .. 1 storm."""
        n = d[155] if len(d) > 155 else 0
        if not 0 < n <= 64 or len(d) < 156 + n * 8:
            return None, None
        soon = later = 0.0
        found = False
        for k in range(n):
            o = 156 + k * 8
            if d[o] != st:
                continue
            found = True
            off, w = d[o + 1], {3: 0.3, 4: 0.7, 5: 1.0}.get(d[o + 2], 0.0)
            if 0 < off <= 10:
                soon = max(soon, w)
            elif 10 < off <= 30:
                later = max(later, w)
        return (soon, later) if found else (None, None)

    def _new_session(self):
        """A new session (or a restart): nothing from the last one may leak into the first frames of this one."""
        self.lap = None
        self.race_over = False
        self.position, self.gap_ahead, self.gap_behind, self.cars = 0, None, None, 0
        self.fuel, self.fuel_cap = 0.0, 0.0
        self.pos, self.right, self.wear, self.others, self.others_meta = None, None, None, None, None
        self.participants, self.car_positions = {}, {}
        self.car_laps, self.events = {}, []
        self.car_ahead = self.car_behind = None
        self.fia_flag = self.sc = None
        self.session, self.race_laps, self.time_left, self.rain = None, 0, None, None
        self.rain_in_10 = self.rain_in_30 = None
        self._sess_ok = False

    def parse(self, d):
        if len(d) < 29:
            return None
        fmt, yr, _ma, _mi, _pv, pid = _U_F1_HDR(d, 0)
        if fmt not in (2023, 2024, 2025) or yr != fmt - 2000 or pid > 15:
            return None
        me = d[27]
        if me >= 22:
            return None
        uid = d[7:15]
        if uid != self._uid and uid != _ZERO8:
            if self._uid is not None:
                self._new_session()
            self._uid = uid
        if pid == 0 and len(d) >= 29 + 22 * 60:
            cars, meta = [], []
            o = 29 + me * 60
            mx, my, mz = self.pos = _U_3f(d, o)
            rx, _ry, rz = _U_3h(d, o + 30)
            self.right = (rx / 32767.0, rz / 32767.0)
            for k in range(22):
                if k == me:
                    continue
                o = 29 + k * 60
                x, y, z = _U_3f(d, o)
                if x or y or z:
                    ddx, ddz = abs(x - mx), abs(z - mz)
                    if ddx <= 10.0 and ddz <= 10.0:
                        cars.append((x, y, z))
                    if ddx <= 25.0 and ddz <= 25.0:
                        nm, tm = self.participants.get(k, (f"Car {k + 1}", "F1 car"))
                        cpos = self.car_positions.get(k, (0, 0.0))[0]
                        meta.append({"pos": (x, y, z), "name": nm, "position": cpos, "car": tm})
            self.others = cars
            self.others_meta = meta or None
            return None
        if pid == 1 and len(d) > 40:
            self._sess_ok = True
            self.track_len = _U_H(d, 33)[0] or None
            self.track = F1_TRACKS.get(_U_b(d, 36)[0], "F1 circuit")
            st = d[35]
            if fmt == 2023:
                self.session = "practice" if 1 <= st <= 4 else "qualifying" if 5 <= st <= 9 else \
                    "race" if 10 <= st <= 12 else None
            else:
                self.session = "practice" if 1 <= st <= 4 else "qualifying" if 5 <= st <= 14 else \
                    "race" if 15 <= st <= 17 else None
            self.race_laps = d[32] if self.session == "race" else 0
            tl = _U_H(d, 38)[0]
            self.time_left = float(tl) if tl and not self.race_laps else None
            self.rain = {3: 0.3, 4: 0.7, 5: 1.0}.get(d[29], 0.0)
            self.sc = {1: "sc", 2: "vsc"}.get(d[153]) if len(d) > 153 else None
            self.rain_in_10, self.rain_in_30 = self._forecast(d, st)
            return None
        if pid == 7:
            per = (len(d) - 29) // 22
            o = 29 + me * per
            if per >= 17 and o + 17 <= len(d):
                self.fuel, self.fuel_cap = _U_2f(d, o + 5)
            if per >= 29 and o + 29 <= len(d):
                self.fia_flag = {2: "blue", 3: "yellow"}.get(_U_b(d, o + 28)[0])
            return None
        if pid == 10:
            per = (len(d) - 29) // 22
            o = 29 + me * per
            if per >= 16 and o + 16 <= len(d):
                w = _U_4f(d, o)
                if all(0.0 <= x <= 100.0 for x in w):
                    self.wear = [w[2], w[3], w[0], w[1]]
            return None
        if pid == 4 and len(d) > 30:
            per = (len(d) - 30) // 22
            if per >= 55:
                for k in range(22):
                    b0 = 30 + k * per
                    if b0 + 55 <= len(d):
                        t_id = d[b0 + 3]
                        nm = _cstr(d, b0 + 7, 48)
                        t_name = F1_TEAMS.get(t_id, "F1 car")
                        if nm:
                            self.participants[k] = (nm, t_name)
            return None
        if pid == 2:
            per = (len(d) - 31) // 22
            if per < 36:
                return None
            o = 29 + me * per
            if fmt == 2023:
                if o + 36 > len(d):
                    return None
                self.lap = _U_II(d, o) + (_f(d, o + 18), d[o + 31], d[o + 32], d[o + 35])
                p_off, ld_off, rs_off = 30, 18, 43

                def gap(base):
                    return _U_H(d, base + 14)[0] / 1000.0
            else:
                if o + 38 > len(d):
                    return None
                self.lap = _U_II(d, o) + (_f(d, o + 20), d[o + 33], d[o + 34], d[o + 37])
                p_off, ld_off, rs_off = 32, 20, 45

                def gap(base):
                    return _U_H(d, base + 14)[0] / 1000.0 + d[base + 16] * 60.0
            self.position = d[o + p_off]
            res_status = d[o + rs_off] if (per > rs_off and o + rs_off < len(d)) else 0
            lapnum_me = self.lap[3]
            self.race_over = bool(self.session == "race" and (
                res_status == 3 or (self.race_laps > 0 and lapnum_me > self.race_laps)
            ))
            ga = gap(o) if self.position > 1 else 0.0
            self.gap_ahead = ga if ga > 0 else None
            self.gap_behind, self.cars = None, 0
            self.car_ahead = self.car_behind = None
            my_ld = self.lap[2]
            tlen = self.track_len or 5000.0
            for k in range(22):
                b0 = 29 + k * per
                if b0 + p_off < len(d) and d[b0 + p_off]:
                    cpos = d[b0 + p_off]
                    cld = _f(d, b0 + ld_off)
                    self.car_positions[k] = (cpos, cld)
                    if b0 + rs_off < len(d):    # lastLapTimeInMS @0; lap number, pit status, pit stops after position
                        self.car_laps[k] = (d[b0 + p_off + 1], d[b0 + p_off + 2], d[b0 + p_off + 3], d[b0 + rs_off],
                                            _U_II(d, b0)[0] / 1000.0)
                    self.cars += 1
                    if self.position > 1 and cpos == self.position - 1:
                        nm, tm = self.participants.get(k, (f"Car {k + 1}", "F1 car"))
                        dm = (cld - my_ld) % tlen
                        self.car_ahead = {"name": nm, "position": cpos, "car": tm,
                                          "distance_m": round(max(1.0, dm)), "gap_s": self.gap_ahead}
                    elif self.position >= 1 and cpos == self.position + 1:
                        g = gap(b0)
                        self.gap_behind = g if g > 0 else None
                        nm, tm = self.participants.get(k, (f"Car {k + 1}", "F1 car"))
                        dm = (my_ld - cld) % tlen
                        self.car_behind = {"name": nm, "position": cpos, "car": tm,
                                           "distance_m": round(max(1.0, dm)), "gap_s": self.gap_behind}
            return None
        if pid == 3 and len(d) >= 33:
            self._event(d)
            return None
        if pid != 6 or self.lap is None or not self._sess_ok or len(d) < 29 + (me + 1) * 60:
            return None
        o = 29 + me * 60
        speed, thr, steer, brk = _U_Hfff(d, o)
        gear = _U_b(d, o + 15)[0]
        rpm = _U_H(d, o + 16)[0]
        t_rl, t_rr, t_fl, t_fr = d[o + 34:o + 38]
        p_rl, p_rr, p_fl, p_fr = _U_4f(d, o + 40)
        eng_t = _U_H(d, o + 38)[0]
        last_ms, cur_ms, lapdist, lapnum, pit, invalid = self.lap
        L = self.track_len or 5000.0
        laps_done = self.race_laps if (self.race_over and self.race_laps > 0) else max(0, lapnum - 1)
        my_team = self.participants.get(me, ("", "F1 car"))[1]
        fr = Frame("F1 25", self.track, my_team, laps_done, max(0.0, lapdist) / L % 1.0, float(speed),
                   thr, brk, steer, gear, float(rpm), cur_ms / 1000.0, last_ms / 1000.0, pit != 0, False,
                   self.fuel, self.track_len, [t_fl, t_fr, t_rl, t_rr], 0.0, None, [p_fl, p_fr, p_rl, p_rr],
                   lap_invalid=invalid != 0)
        fr.session, fr.race_laps, fr.time_left, fr.rain = self.session, self.race_laps, self.time_left, self.rain
        fr.rain_in_10, fr.rain_in_30 = self.rain_in_10, self.rain_in_30
        fr.water_temp = float(eng_t) if 1 < eng_t < 250 else None
        fr.position, fr.cars, fr.gap_ahead, fr.gap_behind = self.position, self.cars, self.gap_ahead, self.gap_behind
        fr.fuel_cap, fr.tyre_wear = self.fuel_cap, self.wear
        fr.pos, fr.right, fr.others, fr.others_meta = self.pos, self.right, self.others, self.others_meta
        fr.race_over = self.race_over
        fr.car_ahead, fr.car_behind = self.car_ahead, self.car_behind
        fr.flag = self.sc or self.fia_flag
        fr.field = self._field(me, L)
        if self.events:
            fr.sim_events, self.events = self.events, []
        return fr

    def _field(self, me, tlen):
        """Every car with a race position. resultStatus: 3 finished, 4 DNF, 5 DSQ, 6 not classified, 7 retired;
        pit status 1 pitting, 2 in the pit area."""
        out = []
        for k, (cpos, cld) in self.car_positions.items():
            lapnum, pit, stops, res, last = self.car_laps.get(k, (1, 0, 0, 2, 0.0))
            if not cpos or res in (0, 1):
                continue
            nm, tm = self.participants.get(k, (f"Car {k + 1}", "F1 car"))
            out.append(field_entry(k, nm, tm, cpos, max(0, lapnum - 1), max(0.0, cld) / tlen, pit != 0, last, None,
                                   {3: "finished", 4: "dnf", 5: "dsq", 6: "dnf", 7: "dnf"}.get(res), stops,
                                   player=k == me))
        return out

    def _event(self, d):
        """Event packet: eventStringCode @29, details @33. Kept as plain dicts with car indexes (= field ids)."""
        code = bytes(d[29:33]).decode("ascii", "ignore")
        n = len(d)
        e = None
        if code == "FTLP" and n >= 38:
            e = {"type": "fastest_lap", "car": d[33], "time": _f(d, 34)}
        elif code == "RTMT":
            e = {"type": "retired", "car": d[33]}
        elif code == "OVTK" and n >= 35:
            e = {"type": "overtake", "car": d[33], "other": d[34]}
        elif code == "COLL" and n >= 35:
            e = {"type": "collision", "car": d[33], "other": d[34]}
        elif code == "PENA" and n >= 40:
            e = {"type": "penalty", "car": d[35], "penalty": d[33], "infringement": d[34], "seconds": d[37]}
        elif code == "SCAR" and n >= 35:
            e = {"type": "safety_car", "kind": {1: "sc", 2: "vsc", 3: "formation"}.get(d[33]),
                 "phase": {0: "deployed", 1: "in", 2: "returned", 3: "resume"}.get(d[34])}
        elif code == "LGOT":
            e = {"type": "lights_out"}
        elif code == "CHQF":
            e = {"type": "chequered"}
        elif code == "RCWN":
            e = {"type": "winner", "car": d[33]}
        elif code == "DRSE":
            e = {"type": "drs", "on": True}
        elif code == "DRSD":
            e = {"type": "drs", "on": False}
        if e is not None:
            self.events = (self.events + [e])[-40:]


class DR2Reader(_UDPReader):
    """DiRT Rally 2.0 'extradata=3' motion packet (SimCoach sets this up in hardware_settings_config.xml)."""
    name = "DiRT Rally 2.0"
    port = 20777
    fallback = 20779
    procs = ("dirtrally2",)

    def __init__(self, port=None, fallback=None):
        self.stage = _StageTracker()
        super().__init__(port, fallback)

    def parse(self, d):
        if len(d) != 264:
            return None
        v = _U_DR2(d, 0)
        L = v[61]
        g = v[33]
        if not (500 < L < 60000 and -200 < v[2] < L + 200 and 0 <= v[1] < 36000 and v[0] >= v[1] - 1
                and 0 <= g <= 10 and g == int(g) and 0 <= v[37] <= 2500 and 0 < v[63] <= 2500):
            return None
        pct = max(0.0, min(0.99999, v[2] / L))
        runs, last, restart = self.stage.step(v[1], pct, int(L), finished=v[2] >= L)
        wk = [abs(v[27]) * 3.6, abs(v[28]) * 3.6, abs(v[25]) * 3.6, abs(v[26]) * 3.6]
        gear = int(v[33]) if v[33] < 9 else -1
        return Frame("DiRT Rally 2.0", f"stage {int(L)} m", "rally car", runs, pct, v[7] * 3.6, v[29], v[31], v[30],
                     gear, v[37] * 10, v[1], last, bool(v[47]), False, v[45], L, None, v[63] * 10, wk, None, restart)


def available_readers(cfg=None, log=print):
    cfg = cfg or {}
    out = []
    if sys.platform != "win32":
        return out
    _UDPPort.share = bool(cfg.get("udp_share_simhub", True))
    _UDPPort.log = staticmethod(log)
    f1 = int(cfg.get("f1_port", 20777))
    dr2_fb = int(cfg.get("dr2_port", 20779))
    makers = [ACReader, ACEvoReader, LMUReader, RF2Reader, AMS2Reader, R3EReader, IRacingReader,
              lambda: EAWRCReader(), lambda: F1Reader(f1, 20778 if f1 != 20778 else None),
              lambda: DR2Reader(20777, dr2_fb if dr2_fb != 20777 else None)]
    for mk in makers:
        try:
            out.append(mk())
        except Exception as e:
            log(f"Reader unavailable: {e}")
    return out


def _plain_name(x):
    import unicodedata
    x = unicodedata.normalize("NFKD", str(x or "")).encode("ascii", "ignore").decode().lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", x).strip() + " "


RACEROOM_CARS_B64 = (
    "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"
)


_R3E = None
_R3E_CLASSES = (   # words in RaceRoom's class name -> SimCoach car class; first match wins
    ("formula", ("formula", "fr", "fr2", "fr3", "frj", "f4", "frx")),
    ("road", ("wtcr", "wtcc", "touring", "tcr", "nationals", "drift", "mx")),
    ("gt4", ("gtr 4", "gt4")),
    ("cup", ("cup", "carrera")),
    ("gte", ("gtr 2", "gte", "gt2", "gtr 1", "gto")),
    ("gt3", ("gtr 3", "gt masters", "gt3", "dtm 2021", "dtm 2023", "dtm 2024", "dtm 2025", "dtm 2026",
             "dtm esports 2022")),
    ("proto", ("p1", "p2", "hypercars", "group c", "dpi")),
)




def _raceroom():
    """({model id: (car name, SimCoach class or None)}, {car name: (model id, SimCoach class or None)}). A car
    that RaceRoom has in several classes gets the class in its name, so every name is one model id."""
    global _R3E
    if _R3E is None:
        try:
            import base64
            import zlib
            raw = json.loads(zlib.decompress(base64.b64decode("".join(RACEROOM_CARS_B64))).decode())
        except Exception:
            raw = {}
        seen = {}
        for name, _c in raw.values():
            seen[name] = seen.get(name, 0) + 1
        by_id, by_name = {}, {}
        for k, (name, cls_name) in raw.items():
            n = _plain_name(cls_name)
            cls = next((c for c, words in _R3E_CLASSES if any(f" {w} " in n for w in words)), None)
            if cls is None:                          # an unusual class: go by the car's own name, if it says
                cn = _plain_name(name)
                cls = next((c for c in ("gt4", "gte", "gt3") if f" {c} " in cn), None)
            shown = f"{name} ({cls_name})" if seen[name] > 1 and cls_name else name
            by_id[int(k)] = (shown, cls)
            by_name[shown] = (int(k), cls)
        _R3E = (by_id, by_name)
    return _R3E


def raceroom_car(model_id):
    """The car's name for a RaceRoom model id ('car 1738' when RaceRoom has added a car SimCoach doesn't know)."""
    hit = _raceroom()[0].get(int(model_id))
    return hit[0] if hit else f"car {int(model_id)}"


def raceroom_class(car):
    """The SimCoach car class of a RaceRoom car name, or None when it isn't known."""
    hit = _raceroom()[1].get(car)
    return hit[1] if hit else None


_RE_NAME_SPLIT = re.compile(r"[_\s]+")
_RE_MODEL_YEAR = re.compile(r"(19|20)\d\d")


_RE_MODEL_YEAR = re.compile(r"(19|20)\d\d")
_MOD_PREFIXES = frozenset(("ks", "rss", "vrc", "urd", "acf", "rt"))


_MOD_PREFIXES = frozenset(("ks", "rss", "vrc", "urd", "acf", "rt"))
_UPPER_TOKENS = frozenset(("bmw", "amg", "gt", "gte", "lmp", "dtm", "rs", "srs", "gtr", "gtd", "vw"))


_UPPER_TOKENS = frozenset(("bmw", "amg", "gt", "gte", "lmp", "dtm", "rs", "srs", "gtr", "gtd", "vw"))


def nice_name(raw):
    """Readable track/car names from game IDs: 'ks_bmw_m4_gt3_2022' -> 'BMW M4 GT3', 'spa' -> 'Spa'."""
    if not raw:
        return ""
    s = str(raw).strip()
    words = [w for w in _RE_NAME_SPLIT.split(s) if w]
    if words and words[0].lower() in _MOD_PREFIXES:
        words = words[1:]
    out = []
    n_words = len(words)
    for w in words:
        lw = w.lower()
        if n_words > 1 and _RE_MODEL_YEAR.fullmatch(lw):
            continue
        if lw in _UPPER_TOKENS or any(ch.isdigit() for ch in lw):
            out.append(lw.upper())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out) or s


UNSUPPORTED_SIMS = (
    ("nascar25", "NASCAR 25", "NASCAR 25 doesn't share any telemetry, so I can't follow the car. Voice questions still work."),
    ("projectmotorracing", "Project Motor Racing",
     "Project Motor Racing's telemetry format isn't published, so I can't read it yet."),
    ("nascarheat5", "NASCAR Heat 5", "I can't read NASCAR Heat 5's telemetry, it only goes to SimHub's own plugin."),
    ("project_k", "KartKraft", "KartKraft isn't supported yet."),
    ("wrcg.exe", "WRC Generations", "WRC Generations isn't supported. EA SPORTS WRC is."),
    ("beamng.drive", "BeamNG.drive", "BeamNG isn't supported."),
)


def unsupported_sim():
    """(name, message) for a running game SimCoach can't read, else None."""
    for exe, name, msg in UNSUPPORTED_SIMS:
        if running(exe):
            return name, msg
    return None

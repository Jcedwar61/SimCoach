"""Commentary when SimCast can only see your car.

SoloTracker: a circuit sim that doesn't share the other cars (AC EVO, ACC without its broadcasting port,
Assetto Corsa without the CrewChiefEx app, any practice on your own). The booth covers your session the way TV
follows one car: laps and personal bests, places gained and lost, the gap to the car ahead closing, pressure
from behind, trips off the track, pit stops, flags and the finish.

RallyTracker: rally stages (EA SPORTS WRC, DiRT Rally 2.0, AC Rally). One car against the clock, like rally
coverage: the stage, the launch, split times against your best run on that stage (kept in stages.json), big
moments, a car stopped on the stage, damage, the finish time and a new stage best.
"""
from __future__ import annotations

import json
import os
import threading

from .race import Car, Event, RaceTracker, call_name
from .sims import field_entry

SPLITS = (0.25, 0.5, 0.75)
PROFILE_STEPS = 100


def _player_entry(f, name):
    return field_entry("me", name, f.car, f.position or 1, f.laps_done, f.pct, f.in_pit, f.last_time or None, None,
                       None, None, player=True, speed=f.speed)


class SoloTracker(RaceTracker):
    solo = True

    def __init__(self, log=print, name_fn=lambda: ""):
        self.name_fn = name_fn
        super().__init__(log=log)

    def reset(self, session=None, track=None):
        super().reset(session, track)
        self.frame = None
        self._pos_seen = None
        self._pos_cand = (None, 0.0)
        self._ahead = self._behind = None
        self._gap_hist = []
        self._off_since = None
        self._off_lap = -1
        self._start_pos = None

    def _name(self, f):
        return (self.name_fn() or "").strip() or (f"the {f.car}" if f.car else "our driver")

    def update(self, f, now):
        if not f:
            return []
        f.field = [_player_entry(f, self._name(f))]
        f.sim_events = None
        prev_frame, self.frame = self.frame, f
        ev = super().update(f, now)
        out = []
        for e in ev:
            if e.kind == "fastest_lap":               # with one car, the 'fastest lap' is a personal best
                if e.data.get("prev") is not None:
                    out.append(Event("personal_best", e.t, 55, e.cars, {"time": e.data["time"]}, ttl=20, key=e.key))
                continue
            if e.kind == "winner":                     # the car we follow finishing isn't 'the winner'
                out.append(Event("player_finish", e.t, 92, e.cars, {"pos": f.position or 0, "grid": self._start_pos},
                                 ttl=40, key="pfin"))
                continue
            if e.kind in ("personal_best", "podium", "player_finish", "battle", "battle_over", "closing", "stretch"):
                continue
            out.append(e)
        if prev_frame is not None and self.session == "race" and self.started:
            out += self._places(f, now)
            out += self._gap_trends(f, now)
        if self.started and self._start_pos is None:
            self._start_pos = f.position or None
        out += self._off(f, now)
        return out

    def _places(self, f, now):
        """Places gained and lost, once the new position has held for a second (no flicker at a pass)."""
        pos = f.position or 0
        if pos <= 0:
            return []
        if self._pos_seen is None:
            self._pos_seen = pos
            return []
        if pos != self._pos_cand[0]:
            self._pos_cand = (pos, now)
            if pos != self._pos_seen:
                self._ahead_then = (self._ahead, self._behind)
        self._ahead = (f.car_ahead or {}).get("name") or self._ahead
        self._behind = (f.car_behind or {}).get("name") or self._behind
        if pos == self._pos_seen or now - self._pos_cand[1] < 1.0 or f.in_pit:
            return []
        was, self._pos_seen = self._pos_seen, pos
        ahead_then, behind_then = getattr(self, "_ahead_then", (None, None))
        if pos < was:
            return [Event("solo_gain", now, 88, ("me",), {"pos": pos, "was": was, "other": ahead_then}, ttl=10,
                          key=f"sg{pos}.{int(now)}")]
        return [Event("solo_loss", now, 84, ("me",), {"pos": pos, "was": was, "other": behind_then}, ttl=10,
                      key=f"sl{pos}.{int(now)}")]

    def _gap_trends(self, f, now):
        """Closing on the car ahead, or under pressure from behind, judged lap by lap."""
        me = self.player()
        if me is None or not self._gap_hist or self._gap_hist[-1][0] != me.laps:
            self._gap_hist.append((me.laps if me else 0, f.gap_ahead, f.gap_behind,
                                   (f.car_ahead or {}).get("name"), (f.car_behind or {}).get("name")))
            del self._gap_hist[:-4]
        else:
            return []
        h = self._gap_hist
        if len(h) < 3 or h[-1][0] - h[-3][0] != 2:
            return []
        out = []
        (_, a0, b0, n0, m0), (_, a2, b2, n2, m2) = h[-3], h[-1]
        if a0 and a2 and n0 and n0 == n2 and 0.8 < a2 < 6.0 and a0 - a2 >= 0.6:
            out.append(Event("solo_closing", now, 70, ("me",), {"gap": a2, "per_lap": (a0 - a2) / 2, "other": n2},
                             ttl=20, key=f"sc{h[-1][0]}"))
        if b0 and b2 and m0 and m0 == m2 and 0.3 < b2 < 4.0 and b0 - b2 >= 0.6:
            out.append(Event("solo_pressure", now, 66, ("me",), {"gap": b2, "per_lap": (b0 - b2) / 2, "other": m2},
                             ttl=20, key=f"sp{h[-1][0]}"))
        return out

    def _off(self, f, now):
        """A trip off the track (the sim says the car is off it) at speed, once per lap."""
        if not f.off_track or f.speed < 40 or f.in_pit:
            self._off_since = None
            return []
        if self._off_since is None:
            self._off_since = now
        if now - self._off_since >= 0.5 and self._off_lap != f.laps_done:
            self._off_lap = f.laps_done
            return [Event("solo_off", now, 74, ("me",), {}, ttl=8, key=f"off{f.laps_done}.{int(now)}")]
        return []


class StageStore:
    """Best runs per stage and car: {key: {"best": seconds, "profile": [seconds at each 1% of the stage]}}."""

    def __init__(self, path=None):
        self.path = path
        self._lock = threading.Lock()
        self.data = {}
        if path:
            try:
                with open(path, encoding="utf-8") as fh:
                    d = json.load(fh)
                self.data = d if isinstance(d, dict) else {}
            except Exception:
                self.data = {}

    def get(self, key):
        return self.data.get(key)

    def offer(self, key, time_s, profile):
        """Keep the run if it's the best on this stage with this car. True when it is."""
        with self._lock:
            cur = self.data.get(key)
            if cur and cur.get("best") and cur["best"] <= time_s:
                return False
            self.data[key] = {"best": round(time_s, 3), "profile": [round(x, 3) if x is not None else None
                                                                   for x in profile]}
            if self.path:
                try:
                    os.makedirs(os.path.dirname(self.path), exist_ok=True)
                    tmp = self.path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as fh:
                        json.dump(self.data, fh)
                    os.replace(tmp, self.path)
                except Exception:
                    pass
            return True


class RallyTracker(RaceTracker):
    rally = True

    def __init__(self, log=print, name_fn=lambda: "", store=None):
        self.name_fn = name_fn
        self.store = store or StageStore()
        super().__init__(log=log)

    def reset(self, session=None, track=None):
        super().reset(session, track)
        self.session = "rally"
        self.key = None
        self.frame = None
        self._run_reset()
        self.top_speed = 0.0

    def _run_reset(self):
        self.running = False
        self.profile = [None] * (PROFILE_STEPS + 1)
        self.splits_told = set()
        self._speed_hist = []
        self._moment_t = -99.0
        self._slow_since = None
        self._stopped = False
        self._damage = None
        self.run_top = 0.0
        self.runs_seen = None

    def update(self, f, now):
        if not f:
            return []
        ev = []
        key = f"{f.game}|{f.track}|{f.car}"
        self.frame = f
        if key != self.key:
            self.reset()
            self.key, self.track, self.game, self.session = key, f.track, f.game, "rally"
            self.track_len = f.track_len or self.track_len
            name = (self.name_fn() or "").strip() or (f"the {f.car}" if f.car and "car" not in f.car else "our driver")
            c = Car("me", {"name": name, "car": f.car, "player": True, "position": 1}, now)
            c.call = call_name(name) if (self.name_fn() or "").strip() else name
            self.cars = {"me": c}
            self.order = ["me"]
            self.player_car = "me"
            best = (self.store.get(key) or {}).get("best")
            ev.append(Event("stage_intro", now, 70, ("me",), {"km": (f.track_len or 0) / 1000.0, "best": best,
                                                              "car": f.car}, ttl=60, key=f"si{key}"))
            self.runs_seen = f.laps_done
        c = self.cars["me"]
        c.speed, c.pct, c.laps = f.speed, f.pct, f.laps_done
        if f.restart and self.running:
            self._run_reset()
            self.runs_seen = f.laps_done
            ev.append(Event("stage_restart", now, 40, ("me",), {}, ttl=10, key=f"rs{int(now)}"))
        if self.runs_seen is None:
            self.runs_seen = f.laps_done
        if f.laps_done > self.runs_seen:                # a run finished (the reader counts it)
            self.runs_seen = f.laps_done
            if self.running:
                ev += self._finish(f, now)
            return ev
        if not self.running:
            if f.cur_time > 0.2 and f.speed > 5 and f.pct < 0.2:
                self.running = True
                self.started = True
                best = (self.store.get(key) or {}).get("best")
                ev.append(Event("stage_start", now, 95, ("me",), {"best": best}, ttl=6, key=f"ss{int(now)}"))
            return ev
        i = int(f.pct * PROFILE_STEPS)
        if 0 <= i <= PROFILE_STEPS and self.profile[i] is None:
            self.profile[i] = f.cur_time
        self.run_top = max(self.run_top, f.speed)
        best = self.store.get(key)
        for sp in SPLITS:
            if f.pct >= sp and sp not in self.splits_told:
                self.splits_told.add(sp)
                ref = best["profile"][int(sp * PROFILE_STEPS)] if best and best.get("profile") else None
                mine = self.profile[int(sp * PROFILE_STEPS)] or f.cur_time
                ev.append(Event("split", now, 72, ("me",), {"at": sp, "time": mine,
                                                             "delta": (mine - ref) if ref else None}, ttl=12,
                                key=f"sp{sp}{int(now)}"))
        ev += self._moments(f, now)
        return ev

    def _moments(self, f, now):
        out = []
        h = self._speed_hist
        h.append((now, f.speed, f.brake))
        while h and now - h[0][0] > 1.2:
            h.pop(0)
        top = max(s for _, s, _ in h)
        braking = max(b for _, _, b in h) > 0.35
        if top - f.speed > 45 and not braking and now - self._moment_t > 10 and f.pct > 0.01:
            self._moment_t = now
            out.append(Event("rally_moment", now, 88, ("me",), {"from": top, "to": f.speed}, ttl=8,
                             key=f"rm{int(now)}"))
        if f.speed < 4 and f.pct > 0.01:
            self._slow_since = self._slow_since or now
            if not self._stopped and now - self._slow_since > 3.0:
                self._stopped = True
                out.append(Event("rally_stopped", now, 90, ("me",), {}, ttl=10, key=f"rst{int(now)}"))
        else:
            if self._stopped and f.speed > 30:
                out.append(Event("rally_going", now, 70, ("me",), {}, ttl=10, key=f"rgo{int(now)}"))
            self._stopped = False
            self._slow_since = None
        if f.damage is not None:
            if self._damage is not None and f.damage - self._damage > 0.08:
                out.append(Event("rally_damage", now, 80, ("me",), {"damage": f.damage}, ttl=10, key=f"rd{int(now)}"))
            self._damage = f.damage
        return out

    def _finish(self, f, now):
        t = f.last_time
        self.running = False
        if not t or t < 10:
            self._run_reset()
            return []
        prev = (self.store.get(self.key) or {}).get("best")
        self.profile[PROFILE_STEPS] = t
        new_best = self.store.offer(self.key, t, self.profile)
        top = self.run_top
        self._run_reset()
        self.runs_seen = f.laps_done
        return [Event("stage_finish", now, 98, ("me",), {"time": t, "best": prev, "new_best": new_best,
                                                          "delta": (t - prev) if prev else None, "top": top},
                      ttl=30, key=f"sf{int(now)}")]

    # the race-only views have nothing to say on a stage
    def standings(self):
        c = self.cars.get("me")
        if c is None:
            return []
        f = self.frame
        return [{"pos": 1, "id": "me", "name": c.name, "call": c.call, "car": c.car, "cls": "", "laps": c.laps,
                 "interval": None, "gap": None, "laps_down": 0, "last": f.last_time if f else None,
                 "best": (self.store.get(self.key) or {}).get("best"), "in_pit": False, "pits": 0, "player": True,
                 "status": "stopped" if self._stopped else None, "battle": False, "grid": None, "fastest": False}]

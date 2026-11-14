"""The race as a TV timing system sees it: every car on the grid, the gaps between them measured at timing loops
around the lap, and the moments a commentator would talk about (overtakes, battles, pit stops, fastest laps,
cars in trouble, the start and the finish).

Input is a sims.Frame with Frame.field (one dict per car, see sims.field_entry). Output is a list of
Events per update. Nothing here talks or plays sound, so it can be tested on its own with a simulated clock.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Optional

N_LOOPS = 40                 # timing loops per lap; gaps are measured where both cars crossed the same loop
UPDATE_EVERY = 0.1           # seconds between updates (the sims send 60 a second; 10 is plenty for timing)
ORDER_SETTLE = 0.8           # a new running order must hold this long before it counts (no flicker at the line)
BATTLE_GAP = 1.0             # within a second: a battle ...
BATTLE_HOLD = 12.0           # ... once it has lasted this long
BATTLE_END_GAP = 1.8
STOPPED_KMH = 25.0
STOPPED_HOLD = 2.5
MOMENT_LOSS = 3.0            # seconds lost over a few loops compared to the lap before: a spin or a trip off
MISSING_HOLD = 8.0           # a car gone from the field this long during a race has retired (or left)
CAUTION_FLAGS = {"fcy", "sc", "vsc"}


@dataclass
class Event:
    kind: str
    t: float
    priority: int
    cars: tuple = ()
    data: dict = field(default_factory=dict)
    ttl: float = 12.0
    key: str = ""

    def age(self, now):
        return now - self.t

    def fresh(self, now):
        return now - self.t <= self.ttl


_SUFFIX = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def call_name(name: str) -> str:
    """How a commentator says a driver's name: the surname ('Max Verstappen' -> 'Verstappen'). Names that are
    already short or are just a number ('Car 7') stay whole; iRacing's trailing digits ('Sam Driver2') go."""
    n = re.sub(r"\s+", " ", (name or "").replace("_", " ")).strip()
    n = re.sub(r"(?<=[A-Za-z])\d+$", "", n)
    parts = n.split(" ")
    if len(parts) < 2 or parts[-1].isdigit() or parts[0].lower() in ("car", "ai", "driver", "#", "the", "our"):
        return n or name
    last = parts[-1]
    if last.lower() in _SUFFIX and len(parts) > 2:
        last = parts[-2]
    return last


class Car:
    def __init__(self, cid, e, now):
        self.id = cid
        self.name = e["name"]
        self.call = call_name(e["name"])
        self.car, self.cls = e.get("car") or "", e.get("cls") or ""
        self.player = bool(e.get("player"))
        self.position = e.get("position") or 0
        self.grid = None
        self.laps = e.get("laps") or 0
        self.pct = e.get("pct") or 0.0
        self.dist: Optional[float] = None
        self._dist_t = now
        self._mismatch_since = None
        self.g = None                                    # last timing loop crossed (laps * N_LOOPS + loop)
        self.cross: dict[int, float] = {}
        self.in_pit = bool(e.get("in_pit"))
        self.status = e.get("status")
        self.last = None
        self.best = None
        self.laps_timed: list[float] = []
        self.lap_start = None
        self.pit_lap = False                             # this lap went through the pit lane
        self.pits = 0
        self.pit_in_t = self.pit_in_pos = None
        self.pit_out_t = None
        self.pit_out_pending = None
        self.speed: Optional[float] = None
        self.slow_since = None
        self.stopped = False
        self.moment_lap = -1
        self.trouble_t = None                            # last stop, spin or recovery: passes on it don't count
        self.seen = now
        self.gone = False
        self.finished = False
        self.interval: Optional[float] = None            # to the car ahead on the road order
        self.gap: Optional[float] = None                 # to the leader
        self.laps_down = 0
        self.mentioned = -1e9

    def __repr__(self):
        return f"<Car {self.call} P{self.position}>"


def ordinal(n):
    n = int(n)
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


class RaceTracker:
    """Feed it frames with update(frame, now); it returns the new Events. Read the state through cars,
    order (ids, leader first), standings(), battles and the session attributes."""

    def __init__(self, log=print):
        self.log = log
        self.reset()

    # ------------------------------------------------------------------ state
    def reset(self, session=None, track=None):
        self.session, self.track = session, track
        self.game = self.player_car = None
        self.cars: dict = {}
        self.order: list = []
        self._cand, self._cand_since = None, 0.0
        self.track_len = 4000.0
        self.race_laps = 0
        self.time_left = None
        self.flag = None
        self.started = False
        self.on_grid = False
        self.start_t = None
        self._start_review_due = None
        self.finished = False
        self.winner = None
        self.fastest = None                              # (time, car id, lap)
        self.battles: dict = {}                          # (ahead id, behind id) -> battle dict
        self._pair_hist: dict = {}                       # (ahead id, behind id) -> [(laps of behind, interval)]
        self._closing_told: dict = {}
        self._stretch_told = -99
        self.leader_laps = 0
        self._time_marks = set()
        self._intro_done = False
        self._last_update = -1e9
        self._sim_keys = {}
        self._first_seen = None
        self._incident = None

    def update(self, f, now) -> list:
        """One frame in, new events out. Frames without a field (sims or sessions SimCoach can't see the whole
        grid in) give no events."""
        if not f or not f.field:
            return []
        session = f.session or "practice"
        if (session != self.session or f.track != self.track or f.restart) and self.session is not None:
            self.log(f"New session: {session} at {f.track}")
            self.reset(session, f.track)
        self.session, self.track, self.game = session, f.track, f.game
        if now - self._last_update < UPDATE_EVERY:
            return []
        dt = now - self._last_update if self._last_update > 0 else UPDATE_EVERY
        self._last_update = now
        if self._first_seen is None:
            self._first_seen = now
        self.track_len = f.track_len or self.track_len
        self.race_laps = f.race_laps or 0
        prev_tl, self.time_left = self.time_left, f.time_left
        ev: list = []
        self._ingest(f.field, now, dt, ev)
        self._sim_events(f.sim_events or [], now, ev)
        if self.session == "race":
            self._race(f, now, prev_tl, ev)
        else:
            self._timed_session(now, ev)
        return ev

    # ------------------------------------------------------------------ cars and timing loops
    def _ingest(self, entries, now, dt, ev):
        seen = set()
        for e in entries:
            cid = e["id"]
            seen.add(cid)
            c = self.cars.get(cid)
            if c is None or c.name != e["name"]:
                c = self.cars[cid] = Car(cid, e, now)
            c.seen, c.gone = now, False
            c.player = bool(e.get("player"))
            if c.player:
                self.player_car = cid
            c.position = e.get("position") or 0
            c.status = e.get("status")
            self._move(c, e, now, dt)
            self._pit(c, bool(e.get("in_pit")), now, ev)
            self._lap(c, e, now, ev)
        for c in self.cars.values():
            if c.id not in seen and not c.gone and now - c.seen > MISSING_HOLD:
                c.gone = True
                if self.session == "race" and self.started and not c.finished and not self.finished:
                    ev.append(Event("retired", now, 75 if c.position <= 3 or c.player else 55, (c.id,),
                                    {"why": "gone", "pos": c.position}, ttl=30, key=f"ret{c.id}"))

    def _move(self, c, e, now, dt):
        raw = (e.get("laps") or 0) + (e.get("pct") or 0.0)
        c.laps, c.pct = e.get("laps") or 0, e.get("pct") or 0.0
        prev = c.dist
        if prev is None:
            dist = raw
        else:
            # The lap counter and the lap fraction don't always change in the same frame at the line: take the
            # reading nearest to where the car was, and only accept a different lap count once it has held.
            dist = min((raw - 1, raw, raw + 1), key=lambda x: abs(x - prev))
            if abs(dist - prev) > 0.3:
                dist = raw                                  # a reset, a teleport to the pits, a new session
            if dist != raw:
                if c._mismatch_since is None:
                    c._mismatch_since = now
                elif now - c._mismatch_since > 1.0:
                    dist = raw
            else:
                c._mismatch_since = None
        if prev is not None and dist < prev - 0.3:
            c.cross.clear()
            c.g = None
        sim_speed = e.get("speed")
        if sim_speed is not None:
            c.speed = sim_speed
        elif prev is not None and dt > 0:
            v = max(0.0, (dist - prev)) * self.track_len / dt * 3.6
            c.speed = v if c.speed is None else c.speed * 0.6 + v * 0.4
        g = int(dist * N_LOOPS)
        if c.g is not None and prev is not None and g > c.g and g - c.g <= N_LOOPS and dist > prev:
            t0 = c._dist_t
            for i in range(c.g + 1, g + 1):
                frac = (i / N_LOOPS - prev) / (dist - prev)
                c.cross[i] = t0 + (now - t0) * min(1.0, max(0.0, frac))
            if len(c.cross) > 4 * N_LOOPS:
                for k in [k for k in c.cross if k < g - 3 * N_LOOPS]:
                    del c.cross[k]
        c.g = g
        c.dist, c._dist_t = dist, now

    def _pit(self, c, in_pit, now, ev):
        racing = self.session == "race" and self.started
        if in_pit and not c.in_pit:
            c.in_pit = True
            c.pit_lap = True
            c.pit_in_t, c.pit_in_pos = now, c.position
            if racing and not c.finished:
                c.pits += 1
                prio = 85 if c.player else 72 if c.position == 1 else 55 if c.position <= 5 else 38
                ev.append(Event("pit_in", now, prio, (c.id,), {"pos": c.position, "stop": c.pits}, ttl=12,
                                key=f"pin{c.id}.{c.pits}"))
        elif not in_pit and c.in_pit:
            c.in_pit = False
            c.pit_out_t = now
            if racing and c.pit_in_t is not None and not c.finished:
                c.pit_out_pending = now + 3.0             # let the running order settle before saying where he is
        if c.pit_out_pending and now >= c.pit_out_pending:
            c.pit_out_pending = None
            took = (c.pit_out_t - c.pit_in_t) if c.pit_in_t else None
            prio = 80 if c.player else 62 if (c.position or 99) <= 3 or (c.pit_in_pos or 99) <= 3 else 40
            ev.append(Event("pit_out", now, prio, (c.id,), {"pos": c.position, "was": c.pit_in_pos,
                                                            "lane_time": took}, ttl=14, key=f"pout{c.id}.{c.pits}"))

    def _lap(self, c, e, now, ev):
        laps = e.get("laps") or 0
        prev_laps = getattr(c, "_laps_seen", None)
        c._laps_seen = laps
        sim_best = e.get("best")
        if prev_laps is None:
            c.lap_start = None
            c.best = sim_best
            return
        if laps <= prev_laps:
            return
        lap_time = e.get("last")
        if lap_time is None or lap_time == c.last:
            lap_time = (now - c.lap_start) if c.lap_start is not None else None
        valid = lap_time is not None and 15.0 < lap_time < 3600.0
        pit_lap, c.pit_lap = c.pit_lap or c.in_pit, c.in_pit
        c.lap_start = now
        if not valid:
            return
        c.last = lap_time
        first_racing_lap = self.session == "race" and laps <= 1
        if not pit_lap and not first_racing_lap:
            c.laps_timed.append(lap_time)
        improved = c.best is None or lap_time < c.best - 1e-3
        if sim_best is not None and (c.best is None or sim_best < c.best):
            c.best = sim_best
        if improved:
            c.best = lap_time if c.best is None else min(c.best, lap_time)
        if self.session != "race":
            return
        if pit_lap or first_racing_lap or self.flag in CAUTION_FLAGS:
            return
        if self.fastest is None or lap_time < self.fastest[0] - 1e-3:
            prev = self.fastest
            self.fastest = (lap_time, c.id, laps)
            prio = 80 if c.player else 60 if c.position <= 5 else 48
            ev.append(Event("fastest_lap", now, prio, (c.id,), {"time": lap_time, "lap": laps,
                                                                 "prev": prev[0] if prev else None,
                                                                 "prev_car": prev[1] if prev else None},
                            ttl=25, key=f"fl{c.id}.{laps}"))
        elif c.player and improved and len(c.laps_timed) >= 2:
            ev.append(Event("personal_best", now, 52, (c.id,), {"time": lap_time}, ttl=20, key=f"pb{laps}"))

    # ------------------------------------------------------------------ order, gaps
    def _sort(self):
        cars = [c for c in self.cars.values() if not c.gone]
        if self.session == "race":
            if cars and all(c.position > 0 for c in cars):
                return [c.id for c in sorted(cars, key=lambda c: c.position)]
            return [c.id for c in sorted(cars, key=lambda c: -(c.dist or 0.0))]
        return [c.id for c in sorted(cars, key=lambda c: (c.best is None, c.best or 0.0, c.position or 999))]

    def _gaps(self):
        order = [self.cars[i] for i in self.order if i in self.cars]
        if not order:
            return
        lead = order[0]
        lead.interval = lead.gap = None
        lead.laps_down = 0
        for a, b in zip(order, order[1:]):
            b.interval = self._time_between(a, b)
            b.gap = self._time_between(lead, b)
            b.laps_down = int((lead.dist or 0) - (b.dist or 0)) if b.gap is None else 0

    @staticmethod
    def _time_between(a, b):
        """Seconds a is ahead of b, measured at the last timing loop b crossed (None if a is a lap or more ahead
        or there's no common loop yet)."""
        if b.g is None or a.dist is None or b.dist is None or a.dist - b.dist >= 1.0:
            return None
        tb, ta = b.cross.get(b.g), a.cross.get(b.g)
        if tb is None or ta is None:
            return None
        return max(0.0, tb - ta)

    # ------------------------------------------------------------------ race logic
    def _race(self, f, now, prev_tl, ev):
        cars = [c for c in self.cars.values() if not c.gone]
        speeds = [c.speed for c in cars if c.speed is not None and not c.in_pit]
        med = statistics.median(speeds) if speeds else 0.0
        leader = self.cars.get(self.order[0]) if self.order else None
        if not self._intro_done:
            self._intro_done = True
            joined = (leader is not None and leader.laps >= 1) or (med > 40 and max((c.laps for c in cars), default=0) > 0)
            self.started = joined
            self.order = self._sort()
            self._gaps()
            ev.append(Event("intro", now, 70, (), {"joined": joined, "cars": len(cars)}, ttl=90, key="intro"))
            if not joined and med < 5:
                self.on_grid = True
        if not self.started:
            if med < 5:
                if not self.on_grid:
                    self.on_grid = True
            elif (self.on_grid and med > 30) or (not self.on_grid and leader and leader.dist and leader.dist >= 1.0):
                self._start(now, ev, standing=self.on_grid)
            for c in cars:
                c.grid = c.position or c.grid
        self._order(now, ev)
        self._gaps()
        if not self.started:
            return
        if self._start_review_due and now >= self._start_review_due:
            self._start_review_due = None
            self._start_review(now, ev)
        self._flags(f, now, ev)
        self._incidents(now, ev)
        self._battles(now, ev)
        self._milestones(f, now, prev_tl, ev)
        self._finish(f, now, ev)

    def _start(self, now, ev, standing=True):
        self.started, self.start_t = True, now
        self._start_review_due = now + 22.0
        for c in self.cars.values():
            c.grid = c.grid or c.position
            c.lap_start = now if standing else c.lap_start
            c.pits = 0
        if not self._sim_keys.get("lights"):
            ev.append(Event("start", now, 100, (), {"standing": standing}, ttl=6, key="start"))

    def _start_review(self, now, ev):
        moves = []
        for c in self.cars.values():
            if c.grid and c.position and not c.gone:
                moves.append((c.grid - c.position, c))
        if not moves:
            return
        moves.sort(key=lambda m: m[0])
        gainer, loser = moves[-1], moves[0]
        me = next((m for m in moves if m[1].player), None)
        ev.append(Event("start_review", now, 74, (), {
            "gainer": gainer[1].id if gainer[0] >= 2 else None, "gained": gainer[0],
            "loser": loser[1].id if loser[0] <= -2 else None, "lost": -loser[0],
            "me": me[1].id if me else None, "me_change": me[0] if me else 0,
            "leader": self.order[0] if self.order else None}, ttl=20, key="startreview"))

    def _order(self, now, ev):
        cand = self._sort()
        if cand != self._cand:
            self._cand, self._cand_since = cand, now
            if self.order and len(self.order) == len(cand) and set(self.order) == set(cand):
                return
        if cand == self.order:
            return
        if self.order and set(self.order) == set(cand) and now - self._cand_since < ORDER_SETTLE:
            return
        old, self.order = self.order, cand
        if not old or not self.started or self.session != "race" or self.finished:
            return
        old_idx = {cid: i for i, cid in enumerate(old)}
        new_idx = {cid: i for i, cid in enumerate(cand)}
        passes: dict = {}
        for i, cid in enumerate(cand):
            j = old_idx.get(cid)
            if j is None or i >= j:
                continue
            a = self.cars[cid]
            for victim in old[:j]:
                if victim not in self.cars or new_idx.get(victim, -1) <= i:
                    continue
                b = self.cars[victim]
                if self._real_pass(a, b, now):
                    passes.setdefault(cid, []).append(victim)
        for cid, victims in passes.items():
            a = self.cars[cid]
            pos = new_idx[cid] + 1
            vs = [self.cars[v] for v in victims]
            involved = a.player or any(v.player for v in vs)
            lead = pos == 1
            prio = 95 if lead else 90 if involved else 80 if pos <= 3 else 66 if pos <= 10 else 48
            gap_before = vs[0].interval if vs else None
            ev.append(Event("overtake", now, prio, (cid,) + tuple(victims),
                            {"pos": pos, "lead": lead, "multi": len(vs) > 1, "battle_len": self._battle_len(vs[0], a, now),
                             "gap_before": gap_before}, ttl=10, key=f"ovt{cid}>{victims[0]}@{int(now)}"))
            for v in victims:
                self._sim_keys.pop(f"ovtk{cid}>{v}", None)

    def _battle_len(self, ahead, behind, now):
        b = self.battles.get((ahead.id, behind.id))
        return now - b["since"] if b else 0.0

    def _real_pass(self, a, b, now):
        """A position change on track, not a pit stop, a stopped car, lapped traffic or a different class."""
        if a.in_pit or b.in_pit or b.stopped or b.finished or a.finished or b.gone or b.status in ("dnf", "dsq"):
            return False
        for c in (a, b):
            if c.pit_in_t is not None and now - c.pit_in_t < 40.0:
                return False
            if c.pit_out_t is not None and now - c.pit_out_t < 25.0:
                return False
        if a.dist is not None and b.dist is not None and abs(a.dist - b.dist) > 0.5:
            return False
        if a.cls and b.cls and a.cls != b.cls:
            return False
        if b.speed is not None and a.speed and b.speed < 0.5 * a.speed:
            return False                                    # b is slowing to a stop: that's an incident, not a pass
        if b.trouble_t is not None and now - b.trouble_t < 12.0:
            return False                                    # b is getting going again after a spin or a stop
        return True

    def _flags(self, f, now, ev):
        fl = f.flag if f.flag in CAUTION_FLAGS else None
        if fl != self.flag:
            prev, self.flag = self.flag, fl
            if fl and not self._sim_keys.get("sc_dep"):
                ev.append(Event("caution", now, 88, (), {"kind": fl}, ttl=15, key=f"caution{int(now)}"))
            elif prev and not fl:
                ev.append(Event("green", now, 86, (), {"was": prev}, ttl=10, key=f"green{int(now)}"))

    def _incidents(self, now, ev):
        for c in self.cars.values():
            if c.gone or c.in_pit or c.finished or c.speed is None or c.status in ("dnf", "dsq"):
                c.slow_since = None
                continue
            pit_recent = c.pit_out_t is not None and now - c.pit_out_t < 8.0
            if c.speed < STOPPED_KMH and not pit_recent and self.flag is None:
                if c.slow_since is None:
                    c.slow_since = now
                elif not c.stopped and now - c.slow_since >= STOPPED_HOLD:
                    c.stopped = True
                    c.moment_lap = c.laps
                    c.trouble_t = now
                    self._incident = (now, c.dist % 1.0 if c.dist is not None else 0.0)
                    prio = 92 if c.player else 86 if c.position <= 3 else 72 if c.position <= 10 else 60
                    ev.append(Event("stopped", now, prio, (c.id,), {"pos": c.position, "lap": c.laps}, ttl=12,
                                    key=f"stop{c.id}.{c.laps}"))
            else:
                if c.stopped and c.speed > 60:
                    c.stopped = False
                    c.trouble_t = now
                    prio = 75 if c.player else 55 if c.position <= 10 else 40
                    ev.append(Event("recovered", now, prio, (c.id,), {"pos": c.position}, ttl=15,
                                    key=f"rec{c.id}.{c.laps}.{int(now)}"))
                c.slow_since = None
            # Time lost in the last few loops compared with the same loops a lap earlier: a spin or a trip off.
            if c.g is None or c.stopped or c.moment_lap == c.laps or self.flag or pit_recent or c.pit_lap:
                continue
            i, w = c.g, 6
            now_seg = (c.cross.get(i), c.cross.get(i - w))
            prev_seg = (c.cross.get(i - N_LOOPS), c.cross.get(i - N_LOOPS - w))
            if None in now_seg or None in prev_seg or c.laps < 1:
                continue
            loss = (now_seg[0] - now_seg[1]) - (prev_seg[0] - prev_seg[1])
            if loss >= MOMENT_LOSS:
                c.moment_lap = c.laps
                c.trouble_t = now
                inc = self._incident
                if inc is not None and now - inc[0] < 12.0:
                    continue        # caught up in an incident just ahead (a car stopped, someone spun): not his own
                self._incident = (now, c.dist % 1.0 if c.dist is not None else 0.0)
                prio = 88 if c.player else 76 if c.position <= 3 else 60 if c.position <= 10 else 45
                ev.append(Event("moment", now, prio, (c.id,), {"loss": loss, "pos": c.position}, ttl=12,
                                key=f"mom{c.id}.{c.laps}"))
        for c in self.cars.values():
            if c.status in ("dnf", "dsq") and not getattr(c, "_ret_told", False) and self.started:
                c._ret_told = True
                if not c.gone:
                    ev.append(Event("retired", now, 75 if c.position <= 3 or c.player else 55, (c.id,),
                                    {"why": c.status, "pos": c.position}, ttl=30, key=f"ret{c.id}"))

    def _battles(self, now, ev):
        order = [self.cars[i] for i in self.order if i in self.cars]
        live = set()
        quiet = self.start_t is not None and now - self.start_t < 40.0    # everyone's nose to tail after the start
        for a, b in zip(order, order[1:]):
            if a.in_pit or b.in_pit or b.interval is None or a.stopped or b.stopped or \
                    a.status in ("dnf", "dsq") or b.status in ("dnf", "dsq") or a.finished or b.finished:
                continue
            key = (a.id, b.id)
            bt = self.battles.get(key)
            if b.interval <= BATTLE_GAP:
                live.add(key)
                if bt is None:
                    bt = self.battles[key] = {"since": now, "told": False, "last_close": now, "pos": b.position}
                bt["last_close"], bt["pos"] = now, b.position
                if not bt["told"] and now - bt["since"] >= BATTLE_HOLD and not quiet:
                    bt["told"] = True
                    involved = a.player or b.player
                    prio = 82 if involved else 70 if a.position == 1 else 62 if a.position <= 3 else 50 if a.position <= 10 else 35
                    ev.append(Event("battle", now, prio, (b.id, a.id), {"pos": a.position, "gap": b.interval}, ttl=20,
                                    key=f"bat{a.id}.{b.id}.{int(bt['since'])}"))
            elif bt is not None and b.interval < BATTLE_END_GAP:
                live.add(key)
            # Closing in: the interval at the end of each of the chaser's laps.
            hist = self._pair_hist.setdefault(key, [])
            if not hist or hist[-1][0] != b.laps:
                hist.append((b.laps, b.interval))
                del hist[:-4]
                if len(hist) >= 3 and hist[-1][0] - hist[-3][0] == 2:
                    gain = hist[-3][1] - hist[-1][1]
                    told = self._closing_told.get(key, -99)
                    if gain >= 0.6 and 1.0 < b.interval < 6.0 and b.laps - told >= 4:
                        self._closing_told[key] = b.laps
                        involved = a.player or b.player
                        prio = 72 if involved else 56 if a.position <= 3 else 44 if a.position <= 10 else 30
                        ev.append(Event("closing", now, prio, (b.id, a.id),
                                        {"gap": b.interval, "per_lap": gain / 2, "pos": a.position}, ttl=20,
                                        key=f"close{a.id}.{b.id}.{b.laps}"))
                    if a.position == 1 and gain <= -1.0 and b.laps - self._stretch_told >= 5 and b.interval > 1.5:
                        self._stretch_told = b.laps
                        ev.append(Event("stretch", now, 46, (a.id, b.id), {"gap": b.interval, "per_lap": -gain / 2},
                                        ttl=25, key=f"str{b.laps}"))
        for key in list(self.battles):
            bt = self.battles[key]
            if key not in live and now - bt["last_close"] > 8.0:
                del self.battles[key]
                a, b = self.cars.get(key[0]), self.cars.get(key[1])
                if not (bt["told"] and a and b) or a.in_pit or b.in_pit or a.gone or b.gone or a.stopped:
                    continue
                if self.pos_of(a.id) and self.pos_of(b.id) and self.pos_of(a.id) < self.pos_of(b.id):
                    ev.append(Event("battle_over", now, 30 if not (a.player or b.player) else 55, (a.id, b.id),
                                    {"gap": b.interval}, ttl=15, key=f"bo{key}{int(now)}"))

    def _milestones(self, f, now, prev_tl, ev):
        leader = self.cars.get(self.order[0]) if self.order else None
        if leader is None or self.finished:
            return
        if leader.laps > self.leader_laps:
            self.leader_laps = leader.laps
            n = leader.laps
            if self.race_laps:
                to_go = self.race_laps - n
                if to_go == 1:
                    ev.append(Event("final_lap", now, 87, (leader.id,), {}, ttl=25, key="finallap"))
                elif to_go in (5, 10) or (to_go == 3 and self.race_laps <= 12):
                    ev.append(Event("laps_to_go", now, 40, (leader.id,), {"to_go": to_go}, ttl=30, key=f"togo{to_go}"))
                elif self.race_laps >= 8 and n == self.race_laps // 2:
                    ev.append(Event("halfway", now, 38, (leader.id,), {}, ttl=30, key="halfway"))
            if n == 1:
                ev.append(Event("lap_one", now, 64, (leader.id,), {}, ttl=25, key="lapone"))
            if self.time_left is not None and self.time_left <= 0 and "last" not in self._time_marks \
                    and not self.race_laps:
                self._time_marks.add("last")
                self._last_lap_at = n
                ev.append(Event("final_lap", now, 87, (leader.id,), {"timed": True}, ttl=25, key="finallap"))
        tl = self.time_left
        if tl is not None and prev_tl is not None and not self.race_laps:
            for mark, label in ((600, "ten minutes"), (300, "five minutes"), (120, "two minutes")):
                if prev_tl > mark >= tl and mark not in self._time_marks:
                    self._time_marks.add(mark)
                    ev.append(Event("time_to_go", now, 42, (leader.id,), {"label": label}, ttl=30, key=f"t{mark}"))

    def _finish(self, f, now, ev):
        leader = self.leader()
        if self.winner is None and leader is not None:
            last_lap_at = getattr(self, "_last_lap_at", None)
            won = leader.status == "finished" or (self.race_laps and leader.laps >= self.race_laps) or \
                (last_lap_at is not None and leader.laps > last_lap_at) or (leader.player and f.race_over)
            if won:
                self.winner, self.finished = leader.id, True
                leader.finished = True
                self._laps_at_win = {c.id: c.laps for c in self.cars.values()}
                ev.append(Event("winner", now, 100, (leader.id,), {}, ttl=30, key="winner"))
        if self.winner is None:
            return
        for c in self.cars.values():
            if c.finished or c.gone:
                continue
            done = c.status == "finished" or c.laps > self._laps_at_win.get(c.id, c.laps) or \
                (c.player and f.race_over)
            if not done:
                continue
            c.finished = True
            pos = self.pos_of(c.id) or c.position
            if c.player:
                ev.append(Event("player_finish", now, 88, (c.id,), {"pos": pos, "grid": c.grid}, ttl=40,
                                key="pfin"))
            elif pos in (2, 3):
                ev.append(Event("podium", now, 90, (c.id,), {"pos": pos}, ttl=45, key=f"pod{pos}"))

    # ------------------------------------------------------------------ qualifying and practice
    def _timed_session(self, now, ev):
        before = list(self.order)
        self.order = self._sort()
        self._gaps_quali()
        if not self._intro_done:
            self._intro_done = True
            ev.append(Event("intro", now, 70, (), {"joined": True, "cars": len(self.cars)}, ttl=90, key="intro"))
            self._best_seen = {c.id: c.best for c in self.cars.values()}
            return
        seen = getattr(self, "_best_seen", {})
        for c in self.cars.values():
            if c.best is not None and c.best != seen.get(c.id):
                old = seen.get(c.id)
                seen[c.id] = c.best
                if old is not None and c.best >= old - 1e-3:
                    continue
                pos = self.order.index(c.id) + 1 if c.id in self.order else 0
                was = before.index(c.id) + 1 if c.id in before and old is not None else None
                top = pos == 1
                quali = self.session == "qualifying"
                prio = (88 if quali else 60) if top else 82 if c.player else (60 if quali else 40) if pos <= 3 else 30
                ev.append(Event("quali_lap", now, prio, (c.id,), {"pos": pos, "was": was, "time": c.best, "top": top},
                                ttl=20, key=f"q{c.id}.{c.best:.3f}"))
        self._best_seen = seen

    def _gaps_quali(self):
        order = [self.cars[i] for i in self.order if i in self.cars]
        top = order[0].best if order and order[0].best else None
        prev = None
        for c in order:
            c.gap = (c.best - top) if (c.best and top) else None
            c.interval = (c.best - prev.best) if (prev and c.best and prev.best) else None
            prev = c

    # ------------------------------------------------------------------ events the sim reports itself
    def _sim_events(self, events, now, ev):
        for e in events:
            k = e.get("type")
            car = self.cars.get(e.get("car"))
            other = self.cars.get(e.get("other"))
            if k == "collision" and car and other and self.started:
                prio = 92 if (car.player or other.player) else 84 if min(car.position, other.position) <= 5 else 66
                ev.append(Event("contact", now, prio, (car.id, other.id), {}, ttl=10, key=f"col{car.id}.{other.id}.{int(now)}"))
            elif k == "accident" and car and self.started:
                prio = 92 if car.player else 82 if car.position <= 5 else 62
                ev.append(Event("accident", now, prio, (car.id,), {"pos": car.position}, ttl=10,
                                key=f"acc{car.id}.{int(now)}"))
            elif k == "penalty" and car and self.started:
                prio = 80 if car.player else 58
                ev.append(Event("penalty", now, prio, (car.id,), {"seconds": e.get("seconds") or 0}, ttl=20,
                                key=f"pen{car.id}.{int(now)}"))
            elif k == "safety_car":
                if e.get("phase") == "deployed" and e.get("kind") in ("sc", "vsc"):
                    self._sim_keys["sc_dep"] = True
                    ev.append(Event("caution", now, 90, (), {"kind": e["kind"]}, ttl=15, key=f"caution{int(now)}"))
                elif e.get("phase") == "in":
                    ev.append(Event("sc_in", now, 80, (), {"kind": e.get("kind")}, ttl=15, key=f"scin{int(now)}"))
            elif k == "lights_out" and not self.started:
                self._sim_keys["lights"] = True
                self._start(now, ev, standing=True)
                ev.append(Event("start", now, 100, (), {"standing": True}, ttl=6, key="start"))

    # ------------------------------------------------------------------ views
    def car(self, cid) -> Optional[Car]:
        return self.cars.get(cid)

    def player(self) -> Optional[Car]:
        return self.cars.get(self.player_car)

    def leader(self) -> Optional[Car]:
        return self.cars.get(self.order[0]) if self.order else None

    def at(self, pos) -> Optional[Car]:
        return self.cars.get(self.order[pos - 1]) if 0 < pos <= len(self.order) else None

    def pos_of(self, cid):
        return self.order.index(cid) + 1 if cid in self.order else 0

    def standings(self):
        out = []
        battling = {i for k in self.battles for i in k if self.battles[k].get("told")}
        for i, cid in enumerate(self.order):
            c = self.cars[cid]
            out.append({"pos": i + 1, "id": cid, "name": c.name, "call": c.call, "car": c.car, "cls": c.cls,
                        "laps": c.laps, "interval": c.interval, "gap": c.gap, "laps_down": c.laps_down,
                        "last": c.last, "best": c.best, "in_pit": c.in_pit, "pits": c.pits, "player": c.player,
                        "status": "finished" if c.finished else ("stopped" if c.stopped else c.status),
                        "battle": cid in battling, "grid": c.grid,
                        "fastest": bool(self.fastest and self.fastest[1] == cid)})
        return out

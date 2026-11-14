"""A made-up race to listen to without a sim (and to test SimCast with): twelve cars on a fictional circuit,
a standing start, cars held up behind slower ones until a passing place, pit stops, one spin, one retirement
and a finish. It produces Frames with the whole field, exactly like a sim reader does."""
from __future__ import annotations

import math
import random

from . import sims

TRACK = "Ridgeway Park"
TRACK_LEN = 3600.0
# (fraction of the lap, apex speed km/h): a quick circuit with two heavy stops into slow corners
CORNERS = [(0.10, 95), (0.24, 160), (0.36, 75), (0.52, 135), (0.63, 185), (0.78, 80), (0.92, 120)]
PASS_ZONES = [(0.04, 0.10), (0.30, 0.36), (0.72, 0.78)]   # the braking zones at the end of the straights
VMAX = 255.0
BRAKE, ACCEL = 13.0, 5.5                                    # m/s^2
PIT_SPEED = 60.0
PIT_ENTRY, PIT_EXIT = 0.955, 0.06
GRID = [
    ("Luca Moretti", 0.990), ("Hana Okafor", 0.992), ("Tomas Lindqvist", 0.995), ("Rafael Duarte", 0.997),
    ("Elena Varga", 1.000), (None, 1.001), ("Kenji Arakawa", 1.004), ("Priya Raman", 1.006),
    ("Oscar Brennan", 1.009), ("Mateo Silva", 1.012), ("Freya Holm", 1.016), ("Dmitri Volkov", 1.020),
]
CAR = "GT3"


def _profile():
    """Speed (km/h) at 1000 points round the lap: the fastest a car can go given the corners ahead and behind."""
    n = 1000
    out = []
    for k in range(n):
        p = k / n
        v = VMAX / 3.6
        for apex, vmin in CORNERS:
            d_to = ((apex - p) % 1.0) * TRACK_LEN
            d_from = ((p - apex) % 1.0) * TRACK_LEN
            vm = vmin / 3.6
            v = min(v, math.sqrt(vm * vm + 2 * BRAKE * d_to), math.sqrt(vm * vm + 2 * ACCEL * d_from))
        out.append(v * 3.6)
    return out


PROFILE = _profile()


def speed_at(p):
    x = (p % 1.0) * len(PROFILE)
    i = int(x)
    a, b = PROFILE[i], PROFILE[(i + 1) % len(PROFILE)]
    return a + (b - a) * (x - i)


def base_lap_time():
    return sum(TRACK_LEN / len(PROFILE) / (v / 3.6) for v in PROFILE)


class DemoCar:
    def __init__(self, k, name, pace, rng, laps=8):
        self.id, self.name, self.pace = k, name, pace
        self.rng = rng
        self.dist = -0.004 * k - 0.002                       # staggered on the grid, behind the line
        self.lap_noise = 1.0
        self.in_pit = False
        self.pit_lap = rng.randint(max(1, int(laps * 0.35)), max(1, min(laps - 2, int(laps * 0.7))))
        self.pitted = False
        self.stop_until = None
        self.stop_left = 0.0
        self.status = None
        self.lap_start = None
        self.last = self.best = None
        self.laps_done = 0
        self.zone_rolled = set()
        self.passing_until = -1.0
        self.speed = 0.0
        self.finished_at = None

    @property
    def laps(self):
        return max(0, int(math.floor(self.dist))) if self.dist >= 0 else 0

    @property
    def pct(self):
        return self.dist % 1.0


class DemoRace:
    """read() gives a Frame each call. dt: seconds of race per call (live: the time since the last call)."""
    name = "Demo"

    def __init__(self, laps=8, seed=7, player_name="", grid_wait=8.0, events=True):
        self.rng = random.Random(seed)
        self.laps = laps
        self.t = 0.0
        self.grid_wait = grid_wait
        self.cars = []
        pname = (player_name or "").strip() or "Sam Carter"
        for k, (name, pace) in enumerate(GRID):
            self.cars.append(DemoCar(k, name or pname, pace * (1 + self.rng.gauss(0, 0.0015)), self.rng, laps))
        self.player = self.cars[5]
        self.player.name = pname
        # Scripted drama so a demo always has some: a spin, a retirement, a fast car starting at the back.
        if events:
            self.spin = (self.cars[2], 3, 0.38)                # car, lap, where
            self.retire = (self.cars[9], max(3, laps - 3), 0.66)
        else:
            self.spin = self.retire = None
        self.cars[11].pace = 0.989                             # a charger from the back
        self.finished = False
        self.done_events = set()
        self.winner_done = False
        self.closed = False

    def connected(self):
        return not self.closed

    def close(self):
        self.closed = True

    # -------------------------------------------------------------- simulation
    def step(self, dt):
        self.t += dt
        started = self.t >= self.grid_wait
        order = sorted(self.cars, key=lambda c: -c.dist)
        for c in self.cars:
            if c.status == "dnf":
                c.speed = 0.0
                continue
            if not started:
                c.speed = 0.0
                continue
            if c.lap_start is None:
                c.lap_start = self.t
            v = speed_at(c.pct) / c.pace / c.lap_noise
            if self.t - self.grid_wait < 6.0:                  # getting away from the grid
                v *= 0.35 + 0.65 * (self.t - self.grid_wait) / 6.0
            # pit stop: through the pit lane on its pit lap
            if c.laps == c.pit_lap and not c.pitted and c.pct >= PIT_ENTRY and c.status is None:
                c.in_pit, c.pitted, c.stop_left = True, True, 7.0 + self.rng.random() * 2.5
            if c.in_pit:
                v = PIT_SPEED
                if c.stop_left > 0 and 0.995 > c.pct > 0.985 or (c.stop_left > 0 and c.pct < 0.01):
                    c.stop_left -= dt
                    v = 0.0
                if PIT_EXIT <= c.pct < 0.5 and c.stop_left <= 0:
                    c.in_pit = False
            if c.finished_at is not None:
                v = min(v, 110.0)                              # cool-down lap
            # scripted spin and retirement
            for what in ("spin", "retire"):
                ev = getattr(self, what)
                if ev and ev[0] is c and c.laps == ev[1] and c.pct >= ev[2] and what not in self.done_events:
                    self.done_events.add(what)
                    c.stop_until = self.t + (6.0 if what == "spin" else 1e9)
                    if what == "retire":
                        c.status = "dnf"
            if c.stop_until is not None and self.t < c.stop_until:
                v = 0.0
            c.speed = v
        # traffic: a car can't drive through the one in front unless it gets a run in a passing zone
        for i, c in enumerate(order):
            if c.speed <= 0 or c.status == "dnf":
                continue
            adv = c.speed / 3.6 * dt / TRACK_LEN
            ahead = next((a for a in order[:i][::-1] if a.status != "dnf" and not a.in_pit and not c.in_pit
                          and a.speed > 40 and 0 < (a.dist - c.dist) * TRACK_LEN < 40), None)
            if ahead is not None and c.finished_at is None and ahead.finished_at is None:
                gap_m = (ahead.dist - c.dist) * TRACK_LEN
                zone = next((z for z in PASS_ZONES if z[0] <= c.pct < z[1]), None)
                if zone is not None and self.t < c.passing_until:
                    pass
                elif zone is not None and (c.laps, zone) not in c.zone_rolled and gap_m < 14:
                    c.zone_rolled.add((c.laps, zone))
                    edge = (ahead.pace * ahead.lap_noise - c.pace * c.lap_noise) * 40
                    if self.rng.random() < max(0.08, min(0.65, 0.12 + edge)):
                        c.passing_until = self.t + 4.0
                if self.t >= c.passing_until:
                    adv = min(adv, max(0.0, (ahead.dist - c.dist) - 9.0 / TRACK_LEN))
            prev_laps = c.laps
            c.dist += adv
            if c.laps > prev_laps and c.dist > 0.5:
                self._line(c)

    def _line(self, c):
        lap_time = self.t - c.lap_start if c.lap_start is not None else None
        c.lap_start = self.t
        c.laps_done = c.laps
        if lap_time and lap_time > 20:
            c.last = lap_time
            c.best = lap_time if c.best is None else min(c.best, lap_time)
        c.lap_noise = 1.0 + abs(self.rng.gauss(0, 0.004))
        if c.status is None and (c.laps >= self.laps or self.winner_done):
            c.status, c.finished_at = "finished", self.t
            self.winner_done = True

    # -------------------------------------------------------------- frames
    def read(self, dt=1 / 30):
        sc = sims
        self.step(dt)
        order = sorted(self.cars, key=lambda c: (c.status == "dnf", c.finished_at is None, c.finished_at or 0.0,
                                                 -c.dist))
        if self.t < self.grid_wait:
            order = list(self.cars)
        pos = {c.id: i + 1 for i, c in enumerate(order)}
        field = [sc.field_entry(c.id, c.name, CAR, pos[c.id], c.laps, c.pct if c.dist >= 0 else c.dist % 1.0,
                                c.in_pit, c.last, c.best, c.status, int(c.pitted and not c.in_pit),
                                player=c is self.player, speed=c.speed, cls="GT3")
                 for c in self.cars]
        p = self.player
        ia = order.index(p)
        ahead = order[ia - 1] if ia > 0 else None
        behind = order[ia + 1] if ia + 1 < len(order) else None
        fr = sc.Frame("Demo", TRACK, "Demo GT3", p.laps, p.pct, p.speed, 1.0, 0.0, 0.0, 4, 7000.0,
                      (self.t - p.lap_start) if p.lap_start else 0.0, p.last or 0.0, p.in_pit, False,
                      track_len=TRACK_LEN, session="race", position=pos[p.id], cars=len(self.cars),
                      race_laps=self.laps)
        fr.field = field
        fr.race_over = p.status == "finished"
        fr.car_ahead = {"name": ahead.name, "position": pos[ahead.id]} if ahead else None
        fr.car_behind = {"name": behind.name, "position": pos[behind.id]} if behind else None
        if all(c.status for c in self.cars) and all(c.finished_at is None or self.t - c.finished_at > 20
                                                    for c in self.cars):
            self.finished = True
        return fr

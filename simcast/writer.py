"""What the commentators say: lines for every kind of race moment, written the way a TV booth talks, in three
voices: the lead (play-by-play), the analyst (colour) and the pit-lane reporter.

These lines are instant (no network), so the big moments are called the moment they happen; the AI booth
(ai.py) adds colour and analysis on top when it's switched on. Drivers are named, never 'he' or 'she': the
sims don't say, and a wrong guess is worse than a name.
"""
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass

LEAD, ANALYST, PIT = "lead", "analyst", "pit"


@dataclass
class Line:
    who: str
    text: str
    energy: int = 1          # 0 calm, 1 engaged, 2 excited, 3 the big moments

    def as_dict(self):
        return {"who": self.who, "text": self.text, "energy": self.energy}


_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth",
        "twelve": "twelfth"}


def num_words(n: int) -> str:
    n = int(n)
    if n < 0:
        return "minus " + num_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + ("-" + _ONES[o] if o else "")
    return str(n)


def ordinal_words(n: int) -> str:
    """5 -> 'fifth', 21 -> 'twenty-first'."""
    w = num_words(n)
    head, _, last = w.rpartition("-")
    if last in _ORD:
        last = _ORD[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return (head + "-" if head else "") + last


def pos_words(p: int) -> str:
    """How a position is said: 'the lead', 'second place', 'P twenty-three' for long grids."""
    if p <= 0:
        return "the pack"
    if p == 1:
        return "the lead"
    if p <= 30:
        return f"{ordinal_words(p)} place"
    return f"P{p}"


def place(p: int) -> str:
    """'second', 'fifth' (no 'place'), for 'running fifth'."""
    return ordinal_words(p) if 0 < p <= 30 else f"P{p}"


def gap_words(s) -> str:
    """Seconds as a commentator says them: 'three tenths', 'half a second', 'one point four seconds'."""
    if s is None:
        return "a gap"
    if s < 0.08:
        return "nothing at all"
    if s < 0.95:
        t = max(1, int(round(s * 10)))
        if t == 5:
            return "half a second"
        return "a tenth" if t == 1 else f"{num_words(t)} tenths"
    if s < 1.05:
        return "a second"
    if s < 10:
        whole, tenth = int(s), int(round((s - int(s)) * 10))
        if tenth == 10:
            whole, tenth = whole + 1, 0
        if tenth == 0:
            return f"{num_words(whole)} seconds"
        if tenth == 5 and whole == 1:
            return "a second and a half"
        return f"{num_words(whole)} point {num_words(tenth)} seconds"
    return f"{num_words(int(round(s)))} seconds" if s < 100 else f"over {int(s // 60)} minutes"


def lap_time_words(t) -> str:
    """69.23 -> 'one nine point two', 103.4 -> 'one forty-three point four', 58.71 -> 'fifty-eight point seven'."""
    if t is None:
        return "a quick one"
    m, sec = divmod(float(t), 60.0)
    tenth = int(round((sec - int(sec)) * 10))
    whole = int(sec)
    if tenth == 10:
        whole, tenth = whole + 1, 0
    if whole == 60:
        m, whole = m + 1, 0
    secw = num_words(whole) if whole >= 10 or m == 0 else f"oh {num_words(whole)}"
    if m == 0:
        return f"{secw} point {num_words(tenth)}"
    return f"{num_words(int(m))} {secw} point {num_words(tenth)}"


def plural(n, word):
    return f"{num_words(n)} {word}" + ("" if n == 1 else "s")


def mins_words(s) -> str:
    m = int(round(s / 60.0))
    if m <= 1:
        return "over a minute" if s >= 60 else "a few laps"
    return f"{num_words(m)} minutes"


class Writer:
    """Turns Events (race.py) into Lines. Keeps track of which phrasings were used lately so the booth doesn't
    sound like a loop, and which drivers were mentioned (the director uses that to spread the airtime)."""

    def __init__(self, tracker, cfg=None, seed=None):
        self.tr = tracker
        self.cfg = cfg or {}
        self.rng = random.Random(seed)
        self._recent: dict = {}

    # ------------------------------------------------------------------ helpers
    @property
    def lead_name(self):
        return (self.cfg.get("lead_name") or "Ben").split()[0]

    @property
    def analyst_name(self):
        return (self.cfg.get("analyst_name") or "Kate").split()[0]

    @property
    def pit_name(self):
        return (self.cfg.get("pit_name") or "Mia").split()[0]

    def pit_voice(self):
        return PIT if self.cfg.get("pit_reporter", True) else LEAD

    def n(self, cid, now=None, full=False):
        """A driver's name as said on air (and marks them as mentioned)."""
        c = self.tr.car(cid)
        if c is None:
            return "a car"
        if now is not None:
            c.mentioned = now
        if c.player and (self.cfg.get("driver_name") or "").strip():
            nm = self.cfg["driver_name"].strip()
            return nm if full else nm.split()[-1] if len(nm.split()) > 1 else nm
        if full:
            return c.name
        same = [o for o in self.tr.cars.values() if o.call == c.call and o.id != c.id and not o.gone]
        return c.name if same else c.call

    def pick(self, kind, options):
        """A random option not used in the last few times for this kind."""
        if not options:
            return None
        recent = self._recent.setdefault(kind, deque(maxlen=max(1, min(4, len(options) - 1))))
        idx = [i for i in range(len(options)) if i not in recent] or list(range(len(options)))
        i = self.rng.choice(idx)
        recent.append(i)
        return options[i]

    def chance(self, p):
        return self.rng.random() < p

    def _race_length(self):
        tr = self.tr
        if tr.race_laps:
            return f"{num_words(tr.race_laps)} laps"
        if tr.time_left:
            return mins_words(tr.time_left)
        return "this race"

    def _lap_status(self):
        tr = self.tr
        ld = tr.leader()
        if ld is None:
            return ""
        lap = ld.laps + 1
        if tr.race_laps:
            return f"lap {num_words(min(lap, tr.race_laps))} of {num_words(tr.race_laps)}"
        return f"lap {num_words(lap)}"

    def _behind(self, cid):
        """(car behind, interval) for cid in the running order."""
        tr = self.tr
        p = tr.pos_of(cid)
        b = tr.at(p + 1)
        return (b, b.interval) if b is not None else (None, None)

    # ------------------------------------------------------------------ events
    def event(self, e, now, interrupting=False) -> list:
        f = getattr(self, "ev_" + e.kind, None)
        lines = f(e, now) if f else []
        lines = [ln for ln in (lines or []) if ln and ln.text]
        if interrupting and lines and lines[0].who == LEAD and lines[0].energy >= 2 and \
                e.kind in ("overtake", "stopped", "moment", "contact", "retired"):
            cut = self.pick("cut", ["Oh, hang on!", "Wait a moment!", "Oh, look at this!", "Hold on!", ""])
            if cut:
                lines[0] = Line(LEAD, f"{cut} {lines[0].text}", lines[0].energy)
        return lines

    def ev_intro(self, e, now):
        tr = self.tr
        track = tr.track or "the circuit"
        if tr.session != "race":
            kind = "qualifying" if tr.session == "qualifying" else "practice"
            return [Line(LEAD, self.pick("intro_q", [
                f"Hello and welcome to {track}, it's {kind}, and {num_words(len(tr.cars))} cars are out to set a time.",
                f"Welcome along to {kind} here at {track}. {num_words(len(tr.cars)).capitalize()} drivers, one clock.",
            ]), 1)]
        if e.data.get("joined"):
            ld = tr.leader()
            p2 = tr.at(2)
            out = [Line(LEAD, self.pick("intro_j", [
                f"And we're joining the action here at {track}, {self._lap_status()}.",
                f"Welcome back to {track}, where we're on {self._lap_status()}.",
            ]), 1)]
            if ld:
                gap = f", {gap_words(p2.interval)} up the road from {self.n(p2.id, now)}" if p2 and p2.interval else ""
                out.append(Line(LEAD, f"{self.n(ld.id, now)} leads{gap}.", 1))
            me = tr.player()
            if me and tr.pos_of(me.id) > 1:
                out.append(Line(ANALYST, f"And {self.n(me.id, now)} is running {place(tr.pos_of(me.id))}.", 1))
            return out
        pole = tr.at(1)
        out = [Line(LEAD, self.pick("intro", [
            f"Hello and welcome to {track}, where {num_words(len(tr.cars))} cars are lining up for {self._race_length()} of racing.",
            f"Good afternoon, and welcome to {track}. {num_words(len(tr.cars)).capitalize()} cars, {self._race_length()}, and it's almost time to go.",
            f"Welcome to {track}. The grid is formed, {num_words(len(tr.cars))} cars, {self._race_length()} ahead of us.",
        ]), 1)]
        bits = []
        if pole:
            bits.append(f"Thanks {self.lead_name}. {self.n(pole.id, now, full=True)} starts from pole")
        me = tr.player()
        if me and pole and me.id != pole.id and tr.pos_of(me.id):
            bits.append(f"and we'll be keeping a close eye on {self.n(me.id, now, full=True)}, "
                        f"lining up {place(tr.pos_of(me.id))} on the grid")
        if bits:
            out.append(Line(ANALYST, ", ".join(bits) + ".", 1))
        return out

    def ev_start(self, e, now):
        if e.data.get("standing", True):
            return [Line(LEAD, self.pick("start", [
                "Lights out, and away we go!",
                "And it's lights out, and the race is on!",
                "Five red lights... and they're away!",
                "Lights out! And we are racing!",
            ]), 3)]
        return [Line(LEAD, self.pick("start_r", [
            "Green flag, green flag, and we are racing!",
            "And the green flag is out, here we go!",
        ]), 3)]

    def ev_start_review(self, e, now):
        d = e.data
        out = []
        if d.get("leader") is not None:
            out.append(Line(LEAD, self.pick("sr_lead", [
                f"Through the opening corners, it's {self.n(d['leader'], now)} who leads.",
                f"{self.n(d['leader'], now)} has the lead as they settle down.",
                f"And {self.n(d['leader'], now)} is out in front.",
            ]), 2))
        if d.get("gainer") is not None:
            out.append(Line(ANALYST, self.pick("sr_gain", [
                f"Great start from {self.n(d['gainer'], now)}, up {plural(d['gained'], 'place')} already.",
                f"What a getaway from {self.n(d['gainer'], now)}, {plural(d['gained'], 'place')} gained.",
            ]), 2))
        if d.get("loser") is not None:
            out.append(Line(ANALYST, self.pick("sr_lose", [
                f"Not such a good one for {self.n(d['loser'], now)}, down {num_words(d['lost'])}.",
                f"{self.n(d['loser'], now)} has gone backwards, {plural(d['lost'], 'place')} lost.",
            ]), 1))
        me = d.get("me")
        if me is not None and me not in (d.get("gainer"), d.get("loser"), d.get("leader")):
            ch = d.get("me_change", 0)
            pos = place(self.tr.pos_of(me))
            txt = (f"{self.n(me, now)} up {num_words(ch)}, into {pos}." if ch > 0 else
                   f"{self.n(me, now)} has dropped {num_words(-ch)}, down to {pos}." if ch < 0 else
                   f"{self.n(me, now)} holds station in {pos}.")
            out.append(Line(LEAD if not out else ANALYST, txt, 1))
        return out

    def ev_overtake(self, e, now):
        d = e.data
        a, victims = e.cars[0], list(e.cars[1:])
        b = victims[0] if victims else None
        an, bn = self.n(a, now), self.n(b, now) if b is not None else "the car ahead"
        pos = d.get("pos", 0)
        ca, cb = self.tr.car(a), self.tr.car(b) if b is not None else None
        if d.get("lead"):
            out = [Line(LEAD, self.pick("ovt_lead", [
                f"And {an} takes the lead! Past {bn}, and into first place!",
                f"There it is! {an} is through on {bn}, and {an} leads the race!",
                f"{an} goes for it... and {an} has the lead!",
                f"It's a new leader! {an} gets the job done on {bn}!",
            ]), 3)]
            if self.chance(0.6):
                out.append(Line(ANALYST, self.pick("ovt_lead_a", [
                    f"That's been coming. {an} has looked the quicker of the two.",
                    f"Big moment in this race. Now can {bn} hang on and fight back?",
                    f"Well, {bn} couldn't hold on to that one. Now {an} has to make it count.",
                ]), 2))
            return out
        if d.get("multi") and len(victims) >= 2:
            names = ", ".join(self.n(v, now) for v in victims[:-1]) + f" and {self.n(victims[-1], now)}"
            return [Line(LEAD, self.pick("ovt_multi", [
                f"{an} is on a charge! Past {names}, all in one go, and up to {place(pos)}!",
                f"Look at {an}! That's {names} dispatched, {an} into {place(pos)}!",
            ]), 3)]
        if ca and ca.player:
            return [Line(LEAD, self.pick("ovt_me", [
                f"{an} makes the move on {bn}! That's {place(pos)} for {an}!",
                f"And {an} is through! Past {bn}, and up into {place(pos)}!",
                f"Lovely move from {an}, {bn} can't do anything about it. {place(pos).capitalize()}!",
            ]), 3)]
        if cb and cb.player:
            return [Line(LEAD, self.pick("ovt_vs_me", [
                f"{an} gets by {bn}, and {bn} drops to {place(pos + 1)}.",
                f"And {bn} has lost a place, {an} is through into {place(pos)}.",
                f"{an} makes it stick on {bn}. That's {place(pos)} for {an}.",
            ]), 2)]
        long_fight = d.get("battle_len", 0) >= 60
        if long_fight:
            return [Line(LEAD, self.pick("ovt_long", [
                f"Finally! After {mins_words(d['battle_len'])} of trying, {an} is past {bn} for {place(pos)}!",
                f"At last, {an} finds a way by {bn}! That's {pos_words(pos)}.",
            ]), 3)]
        energy = 3 if pos <= 3 else 2
        return [Line(LEAD, self.pick("ovt", [
            f"{an} gets past {bn} for {pos_words(pos)}.",
            f"And {an} is through! {pos_words(pos).capitalize()} for {an}, {bn} has no answer.",
            f"Move made by {an} on {bn}, up into {place(pos)}.",
            f"{an} makes it stick on {bn}, and that's {pos_words(pos)}.",
            f"Into {place(pos)} goes {an}, past {bn}.",
            f"Through goes {an}! {bn} loses {pos_words(pos)}.",
        ]), energy)]

    def ev_battle(self, e, now):
        b, a = e.cars
        bn, an = self.n(b, now), self.n(a, now)
        pos, gap = e.data.get("pos", 0), gap_words(e.data.get("gap"))
        what = "the lead" if pos == 1 else place(pos)
        out = [Line(LEAD, self.pick("battle", [
            f"Great scrap developing for {what}: {bn} is right on the back of {an}, just {gap} between them.",
            f"Keep an eye on this one. {bn} is all over {an} in the fight for {what}, {gap} the gap.",
            f"{bn} has closed right up on {an}, {gap} apart, and that's for {what}.",
            f"Now here's a battle: {an} with {bn} in the mirrors, for {what}.",
        ]), 2)]
        if self.chance(0.5):
            out.append(Line(ANALYST, self.pick("battle_a", [
                f"{an} has to be careful now, any small mistake and {bn} is through.",
                f"This is where the pressure tells. {an} can't afford to put a wheel wrong.",
                f"{bn} will be looking for the slipstream. Lovely racing.",
                f"Question is whether {bn} has the pace to actually make a move stick.",
            ]), 1))
        return out

    def ev_closing(self, e, now):
        b, a = e.cars
        d = e.data
        return [Line(self.pick("close_who", [LEAD, ANALYST]), self.pick("closing", [
            f"{self.n(b, now)} is reeling in {self.n(a, now)}, about {gap_words(d['per_lap'])} a lap. The gap's down to {gap_words(d['gap'])}.",
            f"The gap between {self.n(a, now)} and {self.n(b, now)} is coming down, {gap_words(d['gap'])} now.",
            f"{self.n(b, now)} is the quicker car at the moment, closing on {self.n(a, now)}, {gap_words(d['gap'])} the gap.",
        ]), 1)]

    def ev_stretch(self, e, now):
        a, b = e.cars
        return [Line(LEAD, self.pick("stretch", [
            f"{self.n(a, now)} is pulling clear out front, {gap_words(e.data['gap'])} the lead over {self.n(b, now)}.",
            f"The lead is growing. {self.n(a, now)} is {gap_words(e.data['gap'])} up the road now.",
        ]), 1)]

    def ev_battle_over(self, e, now):
        a, b = e.cars
        return [Line(ANALYST, self.pick("bover", [
            f"{self.n(b, now)} has dropped back from {self.n(a, now)}, that fight seems to be over for now.",
            f"{self.n(a, now)} has broken the tow, {self.n(b, now)} just couldn't stay with it.",
        ]), 1)]

    def ev_fastest_lap(self, e, now):
        a = e.cars[0]
        t = lap_time_words(e.data.get("time"))
        c = self.tr.car(a)
        if c and c.player:
            return [Line(LEAD, self.pick("fl_me", [
                f"Purple for {self.n(a, now)}! Fastest lap of the race, a {t}.",
                f"{self.n(a, now)} goes quickest of anyone! A {t}, fastest lap of the race.",
            ]), 2)]
        if e.data.get("prev_car") == a:
            return [Line(LEAD, self.pick("fl_again", [
                f"{self.n(a, now)} goes even quicker, a {t}, and lowers the fastest lap again.",
                f"And another fastest lap for {self.n(a, now)}, now a {t}.",
            ]), 1)]
        out = [Line(LEAD, self.pick("fl", [
            f"Fastest lap of the race goes to {self.n(a, now)}, a {t}.",
            f"{self.n(a, now)} sets the fastest lap, a {t}.",
            f"A {t} for {self.n(a, now)}, quickest lap so far.",
        ]), 1)]
        prev = e.data.get("prev_car")
        if prev is not None and prev != a and self.chance(0.4):
            out.append(Line(ANALYST, f"That beats the {lap_time_words(e.data.get('prev'))} from {self.n(prev, now)}.", 1))
        return out

    def ev_personal_best(self, e, now):
        a = e.cars[0]
        return [Line(ANALYST, self.pick("pb", [
            f"{self.n(a, now)} finding more time there, a {lap_time_words(e.data['time'])}, best lap so far.",
            f"Personal best for {self.n(a, now)}, a {lap_time_words(e.data['time'])}. Getting quicker.",
        ]), 1)]

    def ev_pit_in(self, e, now):
        a = e.cars[0]
        pos = e.data.get("pos", 0)
        c = self.tr.car(a)
        who = self.pit_voice()
        if c and c.player:
            return [Line(who, self.pick("pin_me", [
                f"{self.n(a, now)} is in, here we go. The crew are ready, a crucial stop this.",
                f"And {self.n(a, now)} comes into the pit lane from {place(pos)}.",
            ]), 2)]
        if pos == 1:
            return [Line(who, self.pick("pin_lead", [
                f"The leader is in! {self.n(a, now)} peels into the pit lane.",
                f"{self.n(a, now)} pits from the lead. The crew are out and waiting.",
            ]), 2)]
        return [Line(who, self.pick("pin", [
            f"{self.n(a, now)} pits from {place(pos)}.",
            f"In comes {self.n(a, now)}, who was running {place(pos)}.",
            f"{self.n(a, now)} is in the pit lane.",
        ]), 1)]

    def ev_pit_out(self, e, now):
        a = e.cars[0]
        d = e.data
        pos, was = d.get("pos", 0), d.get("was")
        lane = d.get("lane_time")
        lane_s = f", {num_words(int(round(lane)))} seconds in the pit lane" if lane and lane < 100 else ""
        who = self.pit_voice()
        out = [Line(who, self.pick("pout", [
            f"{self.n(a, now)} is back out, in {place(pos)}{lane_s}.",
            f"Stop done for {self.n(a, now)}, rejoining in {place(pos)}{lane_s}.",
            f"And {self.n(a, now)} is away, back out in {place(pos)}.",
        ]), 1)]
        if was and pos and was < pos and self.chance(0.5):
            out.append(Line(ANALYST, self.pick("pout_a", [
                f"Down from {place(was)} to {place(pos)}, but the others still have to stop.",
                f"That stop costs {self.n(a, now)} {plural(pos - was, 'place')} for now. We'll see how it shakes out.",
            ]), 1))
        return out

    def ev_stopped(self, e, now):
        a = e.cars[0]
        pos = e.data.get("pos", 0)
        c = self.tr.car(a)
        if c and c.player:
            return [Line(LEAD, self.pick("stop_me", [
                f"Oh no! {self.n(a, now)} has stopped on track!",
                f"{self.n(a, now)} is stationary! Trouble for {self.n(a, now)}!",
            ]), 3)]
        return [Line(LEAD, self.pick("stop", [
            f"Oh! {self.n(a, now)} has stopped on track! Trouble for {self.n(a, now)}, who was running {place(pos)}.",
            f"Hang on, {self.n(a, now)} is slow... {self.n(a, now)} has come to a halt!",
            f"{self.n(a, now)} is stationary! That's {self.n(a, now)} from {place(pos)}, stopped out on the circuit.",
        ]), 3)]

    def ev_recovered(self, e, now):
        a = e.cars[0]
        return [Line(LEAD, self.pick("rec", [
            f"{self.n(a, now)} is moving again, but that's cost a lot. Down to {place(e.data.get('pos', 0))}.",
            f"And {self.n(a, now)} gets going again, now {place(e.data.get('pos', 0))}.",
        ]), 1)]

    def ev_moment(self, e, now):
        a = e.cars[0]
        loss = gap_words(e.data.get("loss"))
        c = self.tr.car(a)
        if c and c.player:
            return [Line(LEAD, self.pick("mom_me", [
                f"Big moment for {self.n(a, now)}! That's cost {loss} or so.",
                f"Oh, {self.n(a, now)} has lost time there! {loss.capitalize()} gone.",
            ]), 2)]
        return [Line(LEAD, self.pick("mom", [
            f"Big moment for {self.n(a, now)}! That's cost {loss}.",
            f"{self.n(a, now)} has lost time there, about {loss}. Something's gone wrong.",
            f"Oh! A moment for {self.n(a, now)}, {loss} lost.",
        ]), 2)]

    def ev_retired(self, e, now):
        a = e.cars[0]
        pos = e.data.get("pos", 0)
        if e.data.get("why") == "gone":
            return [Line(LEAD, f"We've lost {self.n(a, now)} from the timing screens. It looks like {self.n(a, now)} has retired.", 1)]
        if e.data.get("why") == "dsq":
            return [Line(LEAD, f"{self.n(a, now)} has been disqualified.", 2)]
        return [Line(LEAD, self.pick("ret", [
            f"And that's the end of the race for {self.n(a, now)}, out from {place(pos)}.",
            f"{self.n(a, now)} is out of the race. A miserable afternoon.",
            f"Retirement for {self.n(a, now)}. That's a real shame.",
        ]), 2)]

    def ev_contact(self, e, now):
        a, b = e.cars
        return [Line(LEAD, self.pick("contact", [
            f"Contact! {self.n(a, now)} and {self.n(b, now)} have touched!",
            f"Oh, they've made contact! {self.n(a, now)} and {self.n(b, now)}!",
        ]), 3)]

    def ev_penalty(self, e, now):
        a = e.cars[0]
        sec = e.data.get("seconds") or 0
        what = f"a {num_words(sec)} second penalty" if 0 < sec < 60 else "a penalty"
        return [Line(LEAD, self.pick("pen", [
            f"News from the stewards: {what} for {self.n(a, now)}.",
            f"And {self.n(a, now)} has been given {what}.",
        ]), 1)]

    def ev_caution(self, e, now):
        k = e.data.get("kind")
        txt = {"sc": "Safety car! The safety car has been deployed!",
               "vsc": "Virtual safety car! Everyone has to slow down.",
               "fcy": "Full course yellow! The race is neutralised."}.get(k, "Yellow flags out on the circuit.")
        return [Line(LEAD, txt, 2)]

    def ev_sc_in(self, e, now):
        return [Line(LEAD, "The safety car is coming in at the end of this lap. Get ready for the restart.", 2)]

    def ev_green(self, e, now):
        return [Line(LEAD, self.pick("green", [
            "And we're green again! Racing resumes!",
            "Green flag! Back to racing!",
        ]), 2)]

    def ev_lap_one(self, e, now):
        tr = self.tr
        p1, p2, p3 = tr.at(1), tr.at(2), tr.at(3)
        if not (p1 and p2):
            return []
        rest = f" and {self.n(p3.id, now)}" if p3 else ""
        out = [Line(LEAD, self.pick("lap1", [
            f"End of the opening lap: {self.n(p1.id, now)} leads {self.n(p2.id, now)}{rest}.",
            f"One lap down. {self.n(p1.id, now)} leads, {self.n(p2.id, now)} second{', ' + self.n(p3.id, now) + ' third' if p3 else ''}.",
        ]), 1)]
        me = tr.player()
        if me and tr.pos_of(me.id) > 3:
            out.append(Line(ANALYST, f"{self.n(me.id, now)} completes the first lap in {place(tr.pos_of(me.id))}.", 1))
        return out

    def ev_laps_to_go(self, e, now):
        tr = self.tr
        p1, p2 = tr.at(1), tr.at(2)
        n = num_words(e.data["to_go"]).capitalize()
        out = [Line(LEAD, f"{n} laps to go, and {self.n(p1.id, now) if p1 else 'the leader'} still leads.", 1)]
        if p2 and p2.interval:
            out.append(Line(ANALYST, f"{self.n(p2.id, now)} is {gap_words(p2.interval)} behind.", 1))
        return out

    def ev_halfway(self, e, now):
        p1, p2 = self.tr.at(1), self.tr.at(2)
        lead = f", {self.n(p1.id, now)} leads by {gap_words(p2.interval)}" if p1 and p2 and p2.interval else ""
        return [Line(LEAD, f"We're at half distance{lead}.", 1)]

    def ev_time_to_go(self, e, now):
        p1 = self.tr.at(1)
        return [Line(LEAD, f"{e.data['label'].capitalize()} left on the clock, and {self.n(p1.id, now) if p1 else 'the leader'} leads.", 1)]

    def ev_final_lap(self, e, now):
        tr = self.tr
        p1, p2 = tr.at(1), tr.at(2)
        out = [Line(LEAD, self.pick("final", [
            f"White flag! This is the final lap, and {self.n(p1.id, now)} leads!",
            f"Here comes the last lap! {self.n(p1.id, now)} is one lap away from victory!",
            "Final lap! One more time round!",
        ]), 2)]
        if p2 and p2.interval is not None:
            if p2.interval < 1.0:
                out.append(Line(ANALYST, f"And {self.n(p2.id, now)} is right there, {gap_words(p2.interval)} behind! This isn't over!", 3))
            else:
                out.append(Line(ANALYST, f"{self.n(p2.id, now)} is {gap_words(p2.interval)} back. {self.n(p1.id, now)} just has to bring it home.", 1))
        return out

    def ev_winner(self, e, now):
        a = e.cars[0]
        c = self.tr.car(a)
        track = self.tr.track or "here"
        win = self.n(a, now, full=True)
        if c and c.player:
            out = [Line(LEAD, self.pick("win_me", [
                f"{win} wins! {win} takes the chequered flag and wins at {track}!",
                f"And it's victory for {win}! What a drive!",
            ]), 3)]
        else:
            out = [Line(LEAD, self.pick("win", [
                f"{win} wins! {win} takes the chequered flag at {track}!",
                f"And it's {win} who takes the win here at {track}!",
                f"Chequered flag! {win} is the winner!",
            ]), 3)]
        if c and c.grid:
            g = c.grid
            line = (f"From pole to the flag. Not a foot wrong from {self.n(a, now)}." if g == 1 else
                    f"From {place(g)} on the grid. What a drive from {self.n(a, now)}." if g >= 4 else
                    f"Started {place(g)}, and took the win. Thoroughly deserved.")
            out.append(Line(ANALYST, line, 2))
        return out

    def ev_podium(self, e, now):
        a = e.cars[0]
        return [Line(LEAD, self.pick("pod", [
            f"{self.n(a, now)} brings it home in {place(e.data['pos'])}.",
            f"Across the line in {place(e.data['pos'])}, {self.n(a, now)}.",
        ]), 1)]

    def ev_player_finish(self, e, now):
        a = e.cars[0]
        pos, grid = e.data.get("pos", 0), e.data.get("grid")
        out = [Line(LEAD, self.pick("pfin", [
            f"And here comes {self.n(a, now, full=True)}, crossing the line in {place(pos)}.",
            f"{self.n(a, now, full=True)} takes the chequered flag in {place(pos)}.",
        ]), 2)]
        if grid and pos:
            if pos < grid:
                out.append(Line(ANALYST, f"Up {plural(grid - pos, 'place')} from {place(grid)} on the grid. A really good afternoon's work.", 2))
            elif pos > grid:
                out.append(Line(ANALYST, f"Down from {place(grid)} on the grid, so a bit of a frustrating one. Plenty to learn from.", 1))
            else:
                out.append(Line(ANALYST, f"Started {place(grid)}, finished {place(pos)}. Solid, and no mistakes when it mattered.", 1))
        return out

    def ev_quali_lap(self, e, now):
        a = e.cars[0]
        d = e.data
        t = lap_time_words(d.get("time"))
        c = self.tr.car(a)
        quali = self.tr.session == "qualifying"
        if d.get("top"):
            return [Line(LEAD, self.pick("q_top", [
                f"{'Provisional pole' if quali else 'Top of the times'} for {self.n(a, now)}! A {t}.",
                f"{self.n(a, now)} goes quickest! A {t}.",
            ]), 2 if quali else 1)]
        if c and c.player:
            return [Line(LEAD, f"{self.n(a, now)} improves, a {t}, that's {place(d.get('pos', 0))}.", 2)]
        return [Line(LEAD, self.pick("q", [
            f"{self.n(a, now)} improves to {place(d.get('pos', 0))}, a {t}.",
            f"A {t} for {self.n(a, now)}, up to {place(d.get('pos', 0))}.",
        ]), 1)]

    # ------------------------------------------------------------------ quiet moments
    def filler(self, now, focus="balanced") -> list:
        """Something to say when nothing's happening: the running order, a battle, the player's race, the pace,
        the pit stops, or a driver who hasn't had a mention for a while."""
        tr = self.tr
        if tr.session != "race":
            return self._filler_quali(now)
        if not tr.started:
            return self._filler_grid(now)
        if tr.finished:
            return []
        weights = {"order": 2, "battle": 3, "player": 3 if focus != "field" else 1, "pace": 1.5,
                   "pits": 1, "field": 2.5 if focus != "me" else 0.5, "lead": 1.5}
        if focus == "me":
            weights["player"] = 6
        opts = list(weights)
        self.rng.shuffle(opts)
        opts.sort(key=lambda k: -weights[k] * self.rng.random())
        for k in opts:
            lines = getattr(self, "_f_" + k)(now)
            if lines:
                return lines
        return []

    def _f_order(self, now):
        tr = self.tr
        top = [tr.at(i) for i in (1, 2, 3)]
        if not all(top):
            return []
        out = [Line(LEAD, self.pick("f_order", [
            f"Let's have a look at the order. {self.n(top[0].id, now)} leads, {self.n(top[1].id, now)} is second, and {self.n(top[2].id, now)} third.",
            f"So, {self._lap_status()}: {self.n(top[0].id, now)}, {self.n(top[1].id, now)}, {self.n(top[2].id, now)}, that's your top three.",
            f"As it stands: {self.n(top[0].id, now)} out in front, then {self.n(top[1].id, now)}, then {self.n(top[2].id, now)}.",
        ]), 1)]
        me = tr.player()
        if me and tr.pos_of(me.id) > 3:
            out += self._player_line(me, now, ANALYST)
        return out

    def _f_lead(self, now):
        p1, p2 = self.tr.at(1), self.tr.at(2)
        if not (p1 and p2) or p2.interval is None:
            return []
        g = gap_words(p2.interval)
        if p2.interval < 1.0:
            return [Line(LEAD, f"Still nothing in it at the front: {self.n(p2.id, now)} is {g} behind {self.n(p1.id, now)}.", 1),
                    Line(ANALYST, f"{self.n(p1.id, now)} can't relax for a second here.", 1)]
        return [Line(LEAD, self.pick("f_lead", [
            f"{self.n(p1.id, now)}'s lead is {g} now.",
            f"Out front, {self.n(p1.id, now)} has {g} in hand over {self.n(p2.id, now)}.",
        ]), 1)]

    def _f_battle(self, now):
        tr = self.tr
        best = None
        for (a, b), bt in tr.battles.items():
            ca, cb = tr.car(a), tr.car(b)
            if not (ca and cb and bt.get("told")) or cb.interval is None or cb.interval > 1.2:
                continue
            score = now - max(ca.mentioned, cb.mentioned) - tr.pos_of(a) * 3
            if best is None or score > best[0]:
                best = (score, ca, cb)
        if best is None or now - max(best[1].mentioned, best[2].mentioned) < 20:
            return []
        _, ca, cb = best
        pos = tr.pos_of(ca.id)
        what = "the lead" if pos == 1 else place(pos)
        return [Line(LEAD, self.pick("f_battle", [
            f"Still a tight one between {self.n(ca.id, now)} and {self.n(cb.id, now)} for {what}, {gap_words(cb.interval)} in it.",
            f"{self.n(cb.id, now)} is still hounding {self.n(ca.id, now)}, {gap_words(cb.interval)} apart, the fight for {what}.",
            f"Let's go back to the battle for {what}. {self.n(ca.id, now)} ahead, {self.n(cb.id, now)} right there, {gap_words(cb.interval)}.",
        ]), 1)]

    def _player_line(self, me, now, who=LEAD):
        tr = self.tr
        p = tr.pos_of(me.id)
        ahead = tr.at(p - 1)
        behind, gb = self._behind(me.id)
        bits = [f"{self.n(me.id, now)} is running {place(p)}"]
        if ahead and me.interval is not None:
            bits.append(f"{gap_words(me.interval)} behind {self.n(ahead.id, now)}")
        if behind and gb is not None and gb < 3:
            bits.append(f"with {self.n(behind.id, now)} {gap_words(gb)} back")
        return [Line(who, ", ".join(bits) + ".", 1)]

    def _f_player(self, now):
        tr = self.tr
        me = tr.player()
        if me is None or me.in_pit or now - me.mentioned < 25:
            return []
        out = self._player_line(me, now)
        if me.last and me.best and len(me.laps_timed) >= 2:
            rank = sorted(c.last for c in tr.cars.values() if c.last and not c.gone and not c.in_pit)
            if rank and me.last <= rank[min(2, len(rank) - 1)]:
                out.append(Line(ANALYST, self.pick("f_me_fast", [
                    f"And {self.n(me.id)} is one of the quickest cars out there at the moment, a {lap_time_words(me.last)} last time round.",
                    f"The pace is there for {self.n(me.id)}. That last lap was a {lap_time_words(me.last)}.",
                ]), 1))
            elif me.interval is not None and me.interval < 1.5:
                out.append(Line(ANALYST, f"Within striking distance. {self.n(me.id)} just needs the right moment.", 1))
        return out

    def _f_pace(self, now):
        tr = self.tr
        laps = [(c.last, c) for c in tr.cars.values() if c.last and not c.gone and not c.in_pit and len(c.laps_timed) >= 1]
        if len(laps) < 3:
            return []
        laps.sort(key=lambda x: x[0])
        t, c = laps[0]
        if now - c.mentioned < 25:
            t, c = laps[1]
        out = [Line(ANALYST, self.pick("f_pace", [
            f"Quickest out there on the last lap was {self.n(c.id, now)}, a {lap_time_words(t)}.",
            f"Interesting, {self.n(c.id, now)} is putting in some quick laps, a {lap_time_words(t)} that last one.",
        ]), 1)]
        if tr.fastest and tr.fastest[1] != c.id:
            out.append(Line(LEAD, f"Fastest lap still belongs to {self.n(tr.fastest[1], now)}, a {lap_time_words(tr.fastest[0])}.", 1))
        return out

    def _f_pits(self, now):
        tr = self.tr
        cars = [c for c in tr.cars.values() if not c.gone and c.status not in ("dnf", "dsq")]
        stopped = [c for c in cars if c.pits]
        if not stopped or len(stopped) == len(cars):
            return []
        still = sorted((c for c in cars if not c.pits), key=lambda c: tr.pos_of(c.id))[:3]
        names = ", ".join(self.n(c.id, now) for c in still)
        return [Line(self.pit_voice(), self.pick("f_pits", [
            f"{num_words(len(stopped)).capitalize()} cars have made their stop so far. Still to come in: {names}.",
            f"In the pit lane, we're waiting on {names}. They're the ones still to stop.",
        ]), 1)]

    def _f_field(self, now):
        """A driver further down who hasn't been mentioned in a while."""
        tr = self.tr
        cands = [c for c in tr.cars.values() if not c.gone and not c.in_pit and tr.pos_of(c.id) > 3 and not c.player
                 and now - c.mentioned > 60 and c.status not in ("dnf", "dsq")]
        if not cands:
            return []
        c = min(cands, key=lambda c: c.mentioned)
        p = tr.pos_of(c.id)
        ahead = tr.at(p - 1)
        gap = f", {gap_words(c.interval)} behind {self.n(ahead.id, now)}" if ahead and c.interval is not None else ""
        extra = ""
        if c.grid and c.grid != p:
            extra = f" Started {place(c.grid)}."
        return [Line(LEAD, self.pick("f_field", [
            f"Further back, {self.n(c.id, now)} is running {place(p)}{gap}.{extra}",
            f"Let's check in on {self.n(c.id, now)}: {place(p)}{gap}.{extra}",
            f"Down in {place(p)}, it's {self.n(c.id, now)}{gap}.{extra}",
        ]), 1)]

    def _filler_grid(self, now):
        tr = self.tr
        if now - getattr(self, "_grid_told", -1e9) < 25:
            return []
        self._grid_told = now
        p1, p2 = tr.at(1), tr.at(2)
        if not (p1 and p2):
            return []
        return [Line(ANALYST, self.pick("grid", [
            f"{self.n(p1.id, now)} and {self.n(p2.id, now)} on the front row. The run to the first corner will be fascinating.",
            "The cars are on the grid. Not long now, everyone's just waiting for the lights.",
        ]), 1)]

    def _filler_quali(self, now):
        tr = self.tr
        p1, p2 = tr.at(1), tr.at(2)
        if not p1 or not p1.best:
            return []
        out = [Line(LEAD, f"{self.n(p1.id, now)} still sets the pace, a {lap_time_words(p1.best)}.", 1)]
        if p2 and p2.gap is not None:
            out.append(Line(ANALYST, f"{self.n(p2.id, now)} is {gap_words(p2.gap)} off that.", 1))
        me = tr.player()
        if me and me.best and tr.pos_of(me.id) > 2 and now - me.mentioned > 30:
            out.append(Line(ANALYST, f"{self.n(me.id, now)} is {place(tr.pos_of(me.id))} for now, {gap_words(me.gap)} off the top.", 1))
        return out

    def wrap_up(self, now):
        tr = self.tr
        w = tr.car(tr.winner)
        if not w:
            return []
        p2, p3 = tr.at(2), tr.at(3)
        pod = f", ahead of {self.n(p2.id, now)}" + (f" and {self.n(p3.id, now)}" if p3 else "") if p2 else ""
        out = [Line(LEAD, f"So, that's the result here at {tr.track or 'the circuit'}: victory for {self.n(w.id, now, full=True)}{pod}.", 1)]
        me = tr.player()
        if me and me.finished:
            out.append(Line(ANALYST, f"And {place(tr.pos_of(me.id))} for {self.n(me.id, now)}. Thanks for watching, everybody.", 1))
        else:
            out.append(Line(ANALYST, f"Great race. Thanks for having me, {self.lead_name}.", 1))
        return out

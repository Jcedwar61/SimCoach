"""The director: decides what goes on air and when, like the producer in a TV booth's ear.

Every tick it looks at the moments the race tracker found and what the booth is doing. The biggest fresh
story goes next; a stale one (an overtake from twenty seconds ago) is dropped; a huge one (a new leader, a car
stopped) cuts in over whatever is being said. In quiet spells the booth talks about the race: battles, gaps,
pace, pit stops, the viewer's own race, and drivers who haven't had a mention, so the whole field gets airtime.
With the AI booth on, the analyst reacts to big moments and the quiet spells become proper conversation.
"""
from __future__ import annotations

from collections import deque

from . import ai as ai_mod
from .race import Event
from .writer import LEAD, Writer

CHATTER = {   # seconds of quiet before the booth fills it, and gap after any line
    "quiet": (28.0, 2.0),
    "normal": (13.0, 1.2),
    "chatty": (6.0, 0.7),
}
FOCUS_BOOST = {"field": 0, "balanced": 10, "me": 22}
CUT_IN = 85                  # events this big may interrupt ...
CUT_MARGIN = 20              # ... something at least this much smaller
REACT_MIN = 60               # the AI analyst reacts to events at least this big
FOLLOWUP_TTL = 12.0
FILLER_TTL = 25.0


class Director:
    def __init__(self, tracker, audio, cfg_fn, booth=None, log=print, seed=None):
        self.tr, self.audio, self.cfg_fn = tracker, audio, cfg_fn
        self.booth = booth                                   # ai.AIBooth or None
        self.log = log
        self.writer = Writer(tracker, cfg_fn(), seed=seed)
        self.pending: list = []
        self._keys: dict = {}
        self.followups: deque = deque()                      # (lines, made, priority)
        self.ai_filler = None                                # (lines, made)
        self.transcript: deque = deque(maxlen=60)            # (who, text) for the AI's memory
        self.recent_events: deque = deque(maxlen=20)
        self.wrapped = False
        self._wrap_asked = None
        self.winner_t = None
        self.last_said_t = -1e9
        self.on_air = True

    # -------------------------------------------------------------- input
    AFTER_FLAG = {"winner", "podium", "player_finish", "retired", "contact", "penalty"}

    def add(self, events, now):
        for e in events:
            if e.key and e.key in self._keys:
                continue
            if self.tr.finished and e.kind not in self.AFTER_FLAG:
                continue                                     # the race is run: no more battle or pace talk
            if e.key:
                self._keys[e.key] = now
            self.pending.append(e)
            try:
                self.recent_events.append(ai_mod.describe(e, self.writer))
            except Exception:
                pass
            if e.kind == "winner":
                self.winner_t = now
        if len(self._keys) > 2000:
            for k in [k for k, t in self._keys.items() if now - t > 600]:
                del self._keys[k]

    def heard(self, line):
        """The audio calls this as each line goes on air."""
        self.transcript.append((line.who, line.text))

    def set_tracker(self, tr):
        self.tr = tr
        self.writer.tr = tr
        self.reset()

    def reset(self):
        self.pending.clear()
        self._keys.clear()
        self.followups.clear()
        self.ai_filler = None
        self.wrapped = False
        self._wrap_asked = None
        self.winner_t = None

    # -------------------------------------------------------------- scoring
    def _score(self, e, now):
        cfg = self.cfg_fn()
        boost = FOCUS_BOOST.get(cfg.get("focus", "balanced"), 10)
        involved = any(getattr(self.tr.car(c), "player", False) for c in e.cars)
        return e.priority + (boost if involved else 0) - e.age(now) * 2.5

    def _best(self, now):
        self.pending = [e for e in self.pending if e.fresh(now) and
                        (not self.tr.finished or e.kind in self.AFTER_FLAG)]
        if not self.pending:
            return None
        return max(self.pending, key=lambda e: self._score(e, now))

    # -------------------------------------------------------------- the loop
    def tick(self, now):
        if not self.on_air:
            self.pending.clear()
            return
        cfg = self.cfg_fn()
        self.writer.cfg = cfg
        quiet_s, gap_s = CHATTER.get(cfg.get("chatter", "normal"), CHATTER["normal"])
        if getattr(self.tr, "solo", False):
            quiet_s *= 1.6                      # one car: less to talk about, so the quiet spells are longer
        top = self._best(now)
        if self.audio.speaking(now):
            if top is not None and top.priority >= CUT_IN and \
                    self._score(top, now) >= self.audio.current_priority + CUT_MARGIN:
                self.audio.interrupt(now)
                self._air_event(top, now, interrupting=True)
            return
        idle = self.audio.idle_for(now)
        if top is not None:
            need = 0.3 if top.priority >= CUT_IN else gap_s
            if idle >= need:
                self._air_event(top, now)
            return
        if self.followups:
            lines, made, prio = self.followups[0]
            if now - made > FOLLOWUP_TTL:
                self.followups.popleft()
            elif idle >= 0.4:
                self.followups.popleft()
                self._air(lines, prio, now)
                if self._wrap_asked is not None:
                    self.wrapped = True
                return
        if self.tr.finished:
            self._wrap(now, idle)
            return
        if idle >= quiet_s * 0.55:
            self._prefetch_filler(now)
        if idle >= quiet_s:
            if self.ai_filler and now - self.ai_filler[1] <= FILLER_TTL:
                lines, _ = self.ai_filler
                self.ai_filler = None
                self._air(lines, 20, now)
                return
            lines = self.writer.filler(now, cfg.get("focus", "balanced"))
            if lines:
                self._air(lines, 20, now)
            else:
                self.audio.last_end = now                    # nothing to say: wait another quiet spell

    # -------------------------------------------------------------- going on air
    def _air(self, lines, priority, now):
        if not lines:
            return
        self.last_said_t = now
        self.audio.say(lines, priority, now)

    def _merge(self, top, now):
        """Several overtakes at once (a train of cars swapping places, a pit cycle): one call, not five."""
        same = [e for e in self.pending if e is not top and e.kind == "overtake" and e.age(now) < 3.0
                and e.priority < 90]
        if top.kind != "overtake" or top.priority >= 90 or not same:
            return None
        events = [top] + same[:2]
        for e in events[1:]:
            self.pending.remove(e)
        w = self.writer
        parts = [f"{w.n(e.cars[0], now)} past {w.n(e.cars[1], now)}" for e in events if len(e.cars) > 1]
        if len(parts) < 2:
            return None
        txt = "Lots going on! " + ", ".join(parts[:-1]) + f", and {parts[-1]}."
        from .writer import Line
        return [Line(LEAD, txt, 2)]

    def _air_event(self, e, now, interrupting=False):
        self.pending.remove(e)
        lines = self._merge(e, now) or self.writer.event(e, now, interrupting=interrupting)
        if not lines:
            return
        self.followups.clear()
        self._air(lines, e.priority, now)
        if e.priority >= REACT_MIN and len(lines) == 1 and e.kind not in ("start", "caution", "green"):
            self._ask_reaction(e, lines[0].text, now)
        if e.kind == "intro" and self.booth is not None:
            self._ask(ai_mod.intro_task(), e.priority - 5, now)

    # -------------------------------------------------------------- AI
    def _brief(self):
        return ai_mod.race_brief(self.tr, self.writer, list(self.recent_events), list(self.transcript))

    def _ask(self, task, priority, now, filler=False):
        if self.booth is None or not self.booth.ready():
            return False
        made = now

        def done(lines, info):
            if filler:
                self.ai_filler = (lines, made)
            else:
                self.followups.append((lines, made, priority))
        try:
            return self.booth.request(task, self._brief(), done)
        except Exception as e:
            self.log(f"AI booth: {e}")
            return False

    def _ask_reaction(self, e, said, now):
        cfg = self.cfg_fn()
        if cfg.get("chatter") == "quiet" and e.priority < 80:
            return
        self._ask(ai_mod.react_task(ai_mod.describe(e, self.writer), said), max(30, e.priority - 30), now)

    def _prefetch_filler(self, now):
        if self.ai_filler is not None and now - self.ai_filler[1] <= FILLER_TTL:
            return
        if self.tr.session == "race" and not self.tr.started:
            return
        self._ask(ai_mod.filler_task(self.writer, now, self.cfg_fn().get("focus", "balanced")), 20, now, filler=True)

    def _wrap(self, now, idle):
        if self.wrapped or self.winner_t is None or now - self.winner_t < 25 or idle < 3:
            return
        if self._wrap_asked is None and self.booth is not None and self._ask(ai_mod.wrap_task(), 40, now):
            self._wrap_asked = now
            return
        if self._wrap_asked is not None and now - self._wrap_asked < 10:
            return                                           # the AI's sign-off is on its way
        self.wrapped = True
        self._air(self.writer.wrap_up(now), 40, now)


def test_event(kind, now, cars=(), **data):
    """Build an Event by hand (tests)."""
    return Event(kind, now, data.pop("priority", 70), tuple(cars), data)

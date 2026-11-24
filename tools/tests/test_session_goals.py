"""Session goals: the corners that cost the most time in one session become the next session's goal; the coach
names it at the start, tracks it lap by lap, says when it's done, and the report and radio answer show it.
Also: Simple view is on for new installs and off for existing ones."""
import json
import os
import tempfile

from _common import check, done, load

sc = load()

GAME, TRACK, CAR, LENGTH = "ACC", "spa", "Porsche 911 GT3 R (992)", 7004
STORE = tempfile.mkdtemp(prefix="simcoach-test-goals-")


class Post(sc.NullOverlay):
    def __init__(self):
        super().__init__()
        self.posts = []

    def post(self, **kw):
        self.posts.append(kw)


def drive(lap_times, slow_at=None, slow=1.0):
    """A session of laps of the given times (the Spa starter profile, scaled). `slow_at` (fraction of a lap,
    from, to) drives that stretch `slow` times slower on every lap after the first, to make one corner cost time."""
    cfg = sc.load_config()
    cfg.update(driver_name="Sam", shared_refs=False, talk_level=1, starter_laps=False)
    voice = sc.Voice(cfg, enabled=False)
    voice.idle = lambda now, v=voice: now >= v.busy_until
    said = []
    voice.log = lambda m: said.append(m)
    ov = Post()
    coach = sc.Coach(cfg, voice, ov, STORE)
    coach.crew = sc.Crew(cfg, voice, ov, coach=coach)
    st = sc.starter_reference("Spa", "gt3")
    prof, base = st["ref"], st["best_time"]
    d, t, lap_t, last, dt, n = 0.0, 0.0, 0.0, 0.0, 1 / 60, 0
    while n < len(lap_times):
        k = base / lap_times[n]
        b = min(sc.BINS - 1, int(d / LENGTH * sc.BINS))
        v = max(10.0, prof["speed"][b] * k)
        if slow_at and n > 0 and slow_at[0] <= d / LENGTH < slow_at[1]:
            v /= slow
        coach.update(sc.Frame(GAME, TRACK, CAR, n, d / LENGTH, v, prof["thr"][b], prof["brk"][b], 0.0, 3, 6000.0,
                              lap_t, last, False, False, fuel=50.0, fuel_cap=100.0, track_len=LENGTH,
                              session="practice"), t)
        t += dt
        lap_t += dt
        d += v / 3.6 * dt
        if d >= LENGTH:
            d -= LENGTH
            n, last, lap_t = n + 1, lap_t, 0.0
    for _ in range(30):
        coach.update(sc.Frame(GAME, TRACK, CAR, n, d / LENGTH, 100.0, 1.0, 0.0, 0.0, 3, 6000.0, lap_t, last, False,
                              False, fuel=50.0, fuel_cap=100.0, track_len=LENGTH, session="practice"), t)
        t += dt
    return coach, said, ov


# session 1: a clean first lap sets the reference, then one stretch of track is driven slower every lap
coach, said, ov = drive([142.0, 142.0, 142.0, 142.0, 142.0], slow_at=(0.30, 0.40), slow=1.06)
check(coach.ref is not None and len(coach.corners) >= 5, f"session 1 mapped the corners ({len(coach.corners)})")
goals = sc.session_goals(coach)
check(goals and goals[0]["loss"] >= sc.GOAL_MIN_LOSS, f"the slow stretch becomes a goal ({goals})")
apex_pct = goals[0]["apex"] / sc.BINS if goals else None
check(apex_pct is not None and 0.28 <= apex_pct <= 0.42, f"in the stretch that was slow (apex at {apex_pct})")
check(all(k in goals[0] for k in ("ci", "apex", "avg", "loss", "issue", "tip", "laps")) if goals else False,
      "a goal has its corner, time and what to fix")
coach.end_session()
sess = coach.past_sessions()
check(sess and sess[-1].get("goals") and sess[-1]["goals"][0]["ci"] == goals[0]["ci"],
      "the goal is saved in the session history")
first_goal = goals[0]["ci"] if goals else None

# carry_goals keeps only goals whose corner is still the same corner
corners = coach.corners
moved = [(s, a + 200, e) for s, a, e in corners]
check(sc.carry_goals(sess, moved) == [], "a goal isn't carried over when the reference's corners have changed")
check(sc.carry_goals([{"date": "x"}], corners) == [], "an old session without goals carries nothing")
check(sc.carry_goals(sess + [{"date": "y", "goals": []}], corners) == [],
      "a later session that met everything leaves no goal")
check(sc.carry_goals([{"goals": [{"ci": "bad"}, {"ci": 999, "apex": 1, "avg": 1}]}], corners) == [],
      "damaged goal entries are skipped")

# session 2, same car and track: the goal is named at the start and tracked; the stretch is now quick
coach2, said2, ov2 = drive([142.0, 141.6, 141.6, 141.6, 141.6])
text2 = " ".join(said2)
check(coach2.goals and coach2.goals[0]["ci"] == first_goal, "session 2 picks up last session's goal")
check("Today's goal from last session" in text2 and f"Turn {first_goal + 1}" in text2,
      "the opening radio call names it")
check(coach2.focus and coach2.focus[0][0] == first_goal or any(
    p.get("focus", "").find(f"Turn {first_goal + 1}") >= 0 for p in ov2.posts), "and it's a focus corner from the start")
prog = sc.goal_progress(coach2)
check(prog and prog[0]["n"] >= 3 and prog[0]["change"] is not None and prog[0]["change"] < 0,
      f"progress: quicker than last session ({prog and prog[0]['change']})")
check(prog and prog[0]["done"], "and the goal is done")
check("Goal done" in text2, "the coach says so once")
check(all(text2.count(f"Goal done: Turn {g['ci'] + 1} ") <= 1 for g in coach2.goals)
      and text2.count("Goal done") <= len(coach2.goals), "once per goal")
goal_posts = [p["goal"] for p in ov2.posts if p.get("goal")]
check(goal_posts and "✓" in goal_posts[-1], f"the Live tab line ticks it off ({goal_posts[-1] if goal_posts else None})")
conv = sc.Conversation(coach2.cfg, coach2, coach2.voice, ov2)
reply = conv.local("what's my goal today")
check(reply and "Today's goal" in reply and "done" in reply, f"'what's my goal' is answered ({reply})")
path = coach2.end_session()
html = open(path, encoding="utf-8").read() if path else ""
check("Goal from last session" in html and "✓ done" in html, "the report has the goal table")
data = coach2.analysis_data(coach2.past_sessions())
check(data.get("goals_from_last_session") and data["goals_from_last_session"][0]["done"] is True,
      "the AI analysis sees the goal")

# Simple view: on for a new install, off for an existing config that predates it
check(sc.load_config()["simple_view"] is True, "no config yet: Simple view")
os.makedirs(os.path.dirname(sc.CONFIG_PATH), exist_ok=True)
json.dump({"driver_name": "Sam"}, open(sc.CONFIG_PATH, "w"))
check(sc.load_config()["simple_view"] is False, "an existing config keeps every tab")
json.dump({"driver_name": "Sam", "simple_view": True}, open(sc.CONFIG_PATH, "w"))
check(sc.load_config()["simple_view"] is True, "and a saved choice is kept")
done()

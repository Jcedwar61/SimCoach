"""Start of every session type: the setup sheet pops up and the strategist + coach briefing is spoken.
(Two simulated minutes per case; a stand-in for the AI briefing covers the background path.)"""
import time

from _common import check, done, headless_coach, load

sc = load()


class Rec(sc.NullOverlay):
    def __init__(self):
        self.posts = []

    def post(self, **kw):
        self.posts.append(kw)


def run(game, session, speed, laps=0, ai_delay=None, chatter="normal", quiet=False, secs=120):
    ov = Rec()
    cfg = sc.load_config()
    cfg.update(driver_name="Sam", openai_api_key="sk-test" if ai_delay is not None else "", crew_chatter=chatter,
               talk_level=0 if quiet else 1)
    cfg, voice, coach = headless_coach(sc, cfg, ov)
    clock = {"t": 0.0}
    said = []
    voice.log = lambda m: said.append(m)
    if ai_delay is not None:
        def fake(api_key, ctx, s, c):
            while clock["t"] < ai_delay:
                time.sleep(0.0005)
            return "AI strategist plan.", "AI coach plan.", "OpenAI test", None
        coach._fetch_openai_setup = fake
    pct = 0.5
    for i in range(60 * secs):
        t = clock["t"] = i / 60
        pct = (pct + speed / 3.6 / 60 / 4000) % 1
        f = sc.Frame(game, "Test Ring", "Test Car", laps, pct, speed, 0.5, 0.0, 0.0, 3, 6000.0, 30.0 + t, 0.0, speed < 1, False,
                     fuel=40.0, fuel_cap=60.0, session=session, position=4, cars=12,
                     race_laps=10 if session == "race" else 0, time_left=1800.0)
        coach.update(f, t)
        coach.crew.update(f, t)
        if ai_delay is not None and abs(t - ai_delay) < 0.05:
            time.sleep(0.2)
    popped = any(p.get("setup_sheet") and p.get("setup_popup") for p in ov.posts)
    strat = any(m.startswith("STRATEGIST") and ("setup for" in m or "AI strategist" in m) for m in said)
    coach_l = any(m.startswith("COACH") and ("Copy Strategist" in m or "AI coach" in m) for m in said)
    return popped, strat, coach_l


for name, args in [("race on the grid", ("ACC", "race", 0.0)), ("rolling start", ("ACC", "race", 120.0)),
                   ("practice in the pits", ("LMU", "practice", 0.0)), ("qualifying on track", ("AMS2", "qualifying", 150.0)),
                   ("rally stage", ("EA WRC", "race", 0.0)), ("no session type", ("AC", None, 60.0)),
                   ("lots of banter", ("ACC", "practice", 120.0, 0, None, "lots")),
                   ("AI briefing 8 s late", ("ACC", "practice", 120.0, 0, 8.0)),
                   ("AI briefing 30 s late", ("ACC", "race", 120.0, 0, 30.0))]:
    popped, s, c = run(*args)
    check(popped and s and c, f"{name}: sheet pops up, strategist and coach heard")
popped, s, c = run("ACC", "race", 120.0, laps=2, secs=5)
check(not popped, "joined after lap 1: sheet waits for a stop")
popped, s, c = run("ACC", "practice", 0.0, quiet=True)
check(s and not c, "Quiet mode: strategist only")
done()

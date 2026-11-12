"""Session starts: full intros + briefing the first time today per car/track, one short line after that;
the briefing modes, the automatic pop-up switch, and "skip the briefing" / "full briefing"."""
import time

from _common import check, done, headless_coach, load

sc = load()


class Rec(sc.NullOverlay):
    def __init__(self):
        self.posts = []

    def post(self, **kw):
        self.posts.append(kw)


def sessions(mode="daily", autopop=True, sessions=("practice", "qualifying"), secs=60):
    ov = Rec()
    cfg = sc.load_config()
    cfg.update(driver_name="Sam", briefing_mode=mode, sheet_autopop=autopop)
    cfg, voice, coach = headless_coach(sc, cfg, ov)
    said = []
    voice.log = lambda m: said.append(m)
    out, t = [], 0.0
    for ses in sessions:
        start, n0 = len(said), len(ov.posts)
        for i in range(60 * secs):
            t += 1 / 60
            f = sc.Frame("ACC", "Spa", "BMW M4 GT3", 0, 0.5, 0.0, 0.0, 0.0, 0.0, 0, 900.0, 10.0 + i / 60, 0.0, True, False,
                         fuel=40.0, fuel_cap=100.0, session=ses, position=3, cars=20, time_left=1800.0)
            coach.update(f, t)
            coach.crew.update(f, t)
        lines = said[start:]
        out.append({"engineer": any(m.startswith("ENGINEER: Engineer on the radio") for m in lines),
                    "full": any(m.startswith("STRATEGIST: Strategist") and "setup for" in m for m in lines)
                    and any(m.startswith("COACH: Copy Strategist") for m in lines),
                    "short": any("Same plan as your earlier session" in m for m in lines),
                    "popup": any(p.get("setup_sheet") and p.get("setup_popup") for p in ov.posts[n0:]),
                    "sheet": any(p.get("setup_sheet") for p in ov.posts[n0:]), "n": len(lines)})
    return out, cfg, voice, coach


r, cfg, voice, coach = sessions()
check(r[0]["engineer"] and r[0]["full"] and r[0]["popup"], "1st session today: intros, full briefing, sheet")
check(not r[1]["engineer"] and not r[1]["full"] and r[1]["short"] and r[1]["popup"], "2nd session: one short line + sheet")
check(r[1]["n"] < r[0]["n"], f"2nd session is quieter ({r[1]['n']} lines vs {r[0]['n']})")
check(time.strftime("%Y-%m-%d") in cfg.get("briefed", {}).values(), "remembered for today")
r, *_ = sessions(mode="always")
check(r[0]["full"] and r[1]["full"], "'Full every session': full both times")
r, *_ = sessions(mode="off")
check(not r[0]["full"] and not r[0]["short"] and r[0]["popup"] and not r[1]["short"], "'Off': no briefing, sheet still shown")
r, *_ = sessions(autopop=False)
check(r[0]["full"] and r[0]["sheet"] and not r[0]["popup"], "pop-up off: briefing heard, sheet ready but not opened")

# skip / full briefing by voice
r, cfg, voice, coach = sessions(sessions=("practice",), secs=2)
conv = sc.Conversation(cfg, coach, voice, sc.NullOverlay())
b = coach.last_setup_briefing
voice._item = (b["strategist"], "urgent", time.monotonic(), None)
reply = conv.local("skip the briefing")
check(reply.startswith("Copy, skipping") and voice._must_stop(False), "'skip the briefing' stops the line playing")
with voice.q.mutex:
    left = [it[0] for it in voice.q.queue]
check(b["coach"] not in left, "and drops the coach's half from the queue")
check(conv.local("skip the briefing") in ("Nothing to skip.", "Copy, skipping it. The sheet's on the setup button."), "skip again is harmless")
said = []
voice.log = lambda m: said.append(m)
check(conv.local("give me the full briefing") == "", "'full briefing' accepted")
time.sleep(0.5)
check(any("setup for" in m for m in said), "full briefing spoken again (not blocked by the earlier skip)")
done()
